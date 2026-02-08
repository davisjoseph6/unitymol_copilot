#!/usr/bin/env python3
"""
unitymol_copilot.nl_backend_molcommandnl

Bridge: UnityMol Copilot -> molcommandnl SemanticInterpreter.

Why this exists:
- Your molcommandnl repo is not a pip-installable package (no setup.py/pyproject.toml).
- Therefore, imports must be done by file-path.

mcp_server calls (per mcp_server.py docstring):
  fn(user_text=..., scene_context=..., dev=...)

We return:
  {
    "success": bool,
    "dsl": str,
    "cleaned_dsl": str,
    "ast": list,
    "error": str,
    "debug": dict
  }

Key fixes (UnityMol Copilot validator grammar):
- `show(sel=..., rep=...)` ONLY supports sel+rep (and requires the comma).
- Color must be applied with:
    color(sel=..., rep=..., color=...)
- Normalize molcommandnl helper lines like:
    update_all_1crn(rep="cartoon", color="red")
  into:
    show(sel="all_1crn", rep="cartoon")
    color(sel="all_1crn", rep="cartoon", color="red")

Also:
- Accept scene context from `scene_context` kwarg (mcp_server), not just `context`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import traceback
from typing import Any, Dict, Optional


# -----------------------------------------------------------------------------
# Repo paths
# -----------------------------------------------------------------------------

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MOLCOMMANDNL_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "molcommandnl"))

# Files we need (path-based import)
_SEMANTIC_INTERPRETER_PY = os.path.join(_MOLCOMMANDNL_ROOT, "script", "semantic_interpreter.py")
_DSL_DEFINITION_PY = os.path.join(_MOLCOMMANDNL_ROOT, "molcommand", "dsl_definition.py")

_INTERPRETER = None
_INIT_ERROR: Optional[Exception] = None


# -----------------------------------------------------------------------------
# Import helpers
# -----------------------------------------------------------------------------

def _load_module_from_path(mod_name: str, path: str):
    """Load a Python module from an absolute file path."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing module file: {path}")

    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for {path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _ensure_root_on_syspath() -> None:
    """
    Ensure molcommandnl root is on sys.path so that relative imports inside
    semantic_interpreter.py (e.g. `from utils import ...`) can resolve.
    """
    if _MOLCOMMANDNL_ROOT not in sys.path:
        sys.path.insert(0, _MOLCOMMANDNL_ROOT)

    script_dir = os.path.join(_MOLCOMMANDNL_ROOT, "script")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)


# -----------------------------------------------------------------------------
# DSL normalization helpers (match unitymol_copilot/validator.py grammar)
# -----------------------------------------------------------------------------

def _parse_kwargs(argstr: str) -> Dict[str, str]:
    """
    Parse key=value kwargs from inside (...) while respecting quotes.

    Returns values as raw strings (including surrounding quotes), e.g.
      sel -> '"all_1crn"'
    """
    args: Dict[str, str] = {}
    buf: list[str] = []
    parts: list[str] = []
    in_q = False
    qch = ""

    for ch in argstr:
        if ch in ('"', "'"):
            if not in_q:
                in_q, qch = True, ch
            elif qch == ch:
                in_q, qch = False, ""
            buf.append(ch)
            continue

        if ch == "," and not in_q:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)

    if buf:
        parts.append("".join(buf).strip())

    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        args[k.strip()] = v.strip()

    return args


def _emit_show_and_optional_color(sel: str, rep: str, color: Optional[str]) -> str:
    """
    Emit valid UnityMol DSL lines:
      show(sel=..., rep=...)
      color(sel=..., rep=..., color=...)   (optional)
    """
    lines = [f"show(sel={sel}, rep={rep})"]
    if color:
        lines.append(f"color(sel={sel}, rep={rep}, color={color})")
    return "\n".join(lines)


def _normalize_to_unitymol_dsl(dsl_text: str) -> str:
    """
    Normalize molcommandnl outputs into UnityMol Copilot validator grammar.

    Rules:
    - update_all_<name>(rep="...", color="...") -> show(sel="all_<name>", rep="...") + color(...)
    - show(sel="...", rep="...", color="...")  -> show(sel="...", rep="...") + color(...)
    - show(...) must ONLY include sel+rep
    - Pass through known valid statements:
        add_structure, hide, select, color_by_chain, color, color_selection
      (and anything else is left as-is, but may later be rejected by the validator)
    """
    if not dsl_text:
        return ""

    out_blocks: list[str] = []
    for raw_line in dsl_text.splitlines():
        line = (raw_line or "").strip()
        if not line or line.startswith("#"):
            continue

        # update_all_NAME(...)
        m = re.match(r"^update_all_(\w+)\((.*)\)\s*$", line)
        if m:
            name = m.group(1)
            args = _parse_kwargs(m.group(2) or "")
            sel = args.get("sel", f'"all_{name}"')
            rep = args.get("rep", '"cartoon"')
            col = args.get("color")
            out_blocks.append(_emit_show_and_optional_color(sel, rep, col))
            continue

        # show(...)
        m = re.match(r"^show\((.*)\)\s*$", line)
        if m:
            args = _parse_kwargs(m.group(1) or "")
            sel = args.get("sel", '"all"')
            rep = args.get("rep", '"cartoon"')
            col = args.get("color")
            out_blocks.append(_emit_show_and_optional_color(sel, rep, col))
            continue

        # Everything else: pass through unchanged
        out_blocks.append(line)

    return "\n".join(out_blocks).strip()


# -----------------------------------------------------------------------------
# Interpreter bootstrapping
# -----------------------------------------------------------------------------

def _build_interpreter():
    """
    Create SemanticInterpreter(dsl, llm) using file-path imports.
    """
    _ensure_root_on_syspath()

    sem_mod = _load_module_from_path("molcommandnl_semantic_interpreter", _SEMANTIC_INTERPRETER_PY)
    dsl_mod = _load_module_from_path("molcommandnl_dsl_definition", _DSL_DEFINITION_PY)

    if not hasattr(sem_mod, "SemanticInterpreter"):
        raise AttributeError("semantic_interpreter.py does not define SemanticInterpreter")
    SemanticInterpreter = getattr(sem_mod, "SemanticInterpreter")

    if not hasattr(dsl_mod, "DSL"):
        raise AttributeError("dsl_definition.py does not define class DSL")
    DSLClass = getattr(dsl_mod, "DSL")
    dsl = DSLClass()

    # semantic_interpreter imports LLMClient via `from llm_client import LLMClient`
    # so llm_client.py must be importable from sys.path (root + script were added)
    try:
        import llm_client  # type: ignore
    except Exception as e:
        raise ImportError(f"Could not import llm_client (check molcommandnl/script): {e}") from e

    if not hasattr(llm_client, "LLMClient"):
        raise AttributeError("llm_client.py does not define LLMClient")
    llm = llm_client.LLMClient()

    return SemanticInterpreter(dsl=dsl, llm=llm)


def _get_interpreter():
    """Cached singleton interpreter; memoize init error to avoid repeated churn."""
    global _INTERPRETER, _INIT_ERROR

    if _INTERPRETER is not None:
        return _INTERPRETER
    if _INIT_ERROR is not None:
        raise _INIT_ERROR

    try:
        _INTERPRETER = _build_interpreter()
        return _INTERPRETER
    except Exception as e:
        _INIT_ERROR = e
        raise


# -----------------------------------------------------------------------------
# Public entrypoint called by mcp_server
# -----------------------------------------------------------------------------

def translate(
    user_text: Optional[str] = None,
    utterance: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Entry point called by UnityMol Copilot (mcp_server).

    mcp_server calls:
      translate(user_text=..., scene_context=..., dev=...)

    We accept:
      - user_text or utterance
      - context or scene_context (kwarg)
      - ignore other kwargs safely
    """
    # Pick up scene context from mcp_server if present.
    scene_ctx = kwargs.get("scene_context")
    if context is None and isinstance(scene_ctx, dict):
        context = scene_ctx

    debug: Dict[str, Any] = {
        "kwargs_keys": sorted(list(kwargs.keys())),
        "molcommandnl_root": _MOLCOMMANDNL_ROOT,
        "semantic_interpreter_py_exists": os.path.isfile(_SEMANTIC_INTERPRETER_PY),
        "dsl_definition_py_exists": os.path.isfile(_DSL_DEFINITION_PY),
        "sys_path_head": sys.path[:6],
        "OLLAMA_HOST": os.environ.get("OLLAMA_HOST", ""),
        "has_context": bool(context),
        "context_schema": (context or {}).get("schema") if isinstance(context, dict) else None,
    }

    try:
        interp = _get_interpreter()

        text = user_text if user_text is not None else (utterance or "")
        text = str(text).strip()
        debug["user_text_preview"] = text[:160]

        # Pass scene context through; SemanticInterpreter decides whether to use it.
        res = interp.interpret(utterance=text, context=context)

        dsl_out = (res.get("dsl", "") or getattr(res, "program", "") or "").strip()
        cleaned_out = (res.get("cleaned_dsl", "") or getattr(res, "cleaned_program", "") or "").strip()
        ast_out = res.get("ast", [])

        # Normalize to UnityMol validator grammar
        dsl_out = _normalize_to_unitymol_dsl(dsl_out)
        cleaned_out = _normalize_to_unitymol_dsl(cleaned_out)

        debug["dsl_len"] = len(dsl_out)
        debug["cleaned_len"] = len(cleaned_out)
        debug["ast_len"] = len(ast_out) if isinstance(ast_out, list) else None

        if not dsl_out:
            return {
                "success": False,
                "dsl": "",
                "cleaned_dsl": "",
                "ast": [],
                "error": (
                    "Empty DSL produced.\n"
                    "Most common causes:\n"
                    "  - LLM returned nothing (ollama/model not reachable)\n"
                    "  - DSL.extract_dsl_lines filtered everything\n"
                    "  - DSL/rules mismatch\n"
                    "Check debug + molcommandnl logs."
                ),
                "debug": debug,
            }

        return {
            "success": True,
            "dsl": dsl_out,
            "cleaned_dsl": cleaned_out,
            "ast": ast_out,
            "error": "",
            "debug": debug,
        }

    except Exception as e:
        return {
            "success": False,
            "dsl": "",
            "cleaned_dsl": "",
            "ast": [],
            "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            "debug": debug,
        }

