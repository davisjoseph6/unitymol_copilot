#!/usr/bin/env python3
"""
UnityMol Copilot - Updated implementation using FastMCP

Step 2 (robust color/show/hide) is implemented here.
Step 3 (NL -> DSL -> execution) is implemented here via `execute_nl`.

Important Step 2 / DSL integration fix:
- After robust loading completes, always create a stable alias selection named:
    all_<requested_pdbid>
  so downstream DSL can refer to all_1crn, all_1kx2, etc., even if UnityMol
  internally names the structure instance 1kx2_2.

Loader strategy (robust in your environment):
---------------------------------------------
0) Try local Windows file load first:
      load("C:/Users/<WIN_USER>/unitymol_data/<pdbid>.pdb")
   (override directory via UMOL_WIN_PDB_DIR)

1) If local load fails, try UnityMol fetch():
      fetch("<pdbid>", True/False)

2) If fetch fails, download from RCSB and load via loadFromString().

Notes:
- The alias selection uses select("all", "all_<pdbid>") which selects all atoms
  currently loaded. If multiple structures are loaded simultaneously,
  "all_<pdbid>" will not be structure-scoped unless you introduce a
  structure-scoped selection query.

Step 3: NL -> DSL translation (pluggable backends)
-------------------------------------------------
Choose a backend:

A) Local HTTP translator (recommended)
   - Set:
       UMOL_NL_BACKEND=http
       UMOL_NL_ENDPOINT=http://127.0.0.1:8000/translate
   - The server will POST JSON:
       {
         "user_text": "...",
         "scene_context": {...},
         "dev": true/false
       }
     and expects JSON back like:
       { "dsl": "...", "meta": {...} }

B) OpenAI backend (optional)
   - Set:
       UMOL_NL_BACKEND=openai
       OPENAI_API_KEY=...
       UMOL_OPENAI_MODEL=gpt-4.1-mini   (or any model you use)
   - Requires `openai` python package installed in your venv.

C) Python module callable (optional)
   - Set:
       UMOL_NL_BACKEND=python
       UMOL_NL_PY_MODULE=your_module
       UMOL_NL_PY_FUNC=your_callable
   - Callable signature should be:
       your_callable(user_text: str, scene_context: dict, dev: bool) -> str | dict
     If dict is returned, it should include key "dsl".

If no backend is configured, `execute_nl` returns a helpful error message.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import time
import urllib.request
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

from unitymol_zmq import UnityMolZMQ
from validator import parse_and_validate_molcommand
from executor import dsl_to_zmq_calls
from dsl_normalizer import normalize_dsl, dev_mode_enabled
from scene_context import build_scene_context

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("UnityMolCopilot")

# FastMCP server
mcp = FastMCP("unitymol-copilot")

# Global UnityMolZMQ instance
unitymol: UnityMolZMQ | None = None

# Recent actions buffer
RECENT_ACTIONS: deque = deque(maxlen=40)

# Loader polling knobs
POLL_INTERVAL_S: float = float(os.environ.get("UMOL_POLL_INTERVAL_S", "0.4"))
DEFAULT_LOAD_TIMEOUT_S: float = float(os.environ.get("UMOL_LOAD_TIMEOUT_S", "20.0"))

# Local-load knobs (Windows paths; used from WSL)
WIN_USER: str = os.environ.get("WIN_USER", "").strip()  # optional
UMOL_WIN_PDB_DIR: str = os.environ.get("UMOL_WIN_PDB_DIR", "").strip()  # optional override

# NL translation knobs
NL_BACKEND: str = os.environ.get("UMOL_NL_BACKEND", "").strip().lower()  # http | openai | python
NL_ENDPOINT: str = os.environ.get("UMOL_NL_ENDPOINT", "").strip()        # for http backend
OPENAI_MODEL: str = os.environ.get("UMOL_OPENAI_MODEL", "gpt-4.1-mini").strip()
PY_MOD: str = os.environ.get("UMOL_NL_PY_MODULE", "").strip()
PY_FUNC: str = os.environ.get("UMOL_NL_PY_FUNC", "").strip()

# Special directives emitted by executor
_LOAD_DIRECTIVE_RE = re.compile(r'__LOAD_STRUCTURE__\(\s*["\']([^"\']+)["\']\s*\)\s*$')
_COLOR_DIRECTIVE_RE = re.compile(
    r'__COLOR_SELECTION__\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)\s*$'
)

_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,80}$")


def _stdout_has_problem(stdout: str) -> bool:
    s = (stdout or "").replace("\r", "")
    return ("[Warning]" in s) or ("[Error]" in s)


def _effective_success(payload: Dict[str, Any]) -> bool:
    """UnityMol may report success=True while stdout contains warnings/errors."""
    if not bool(payload.get("success", False)):
        return False
    if _stdout_has_problem(payload.get("stdout", "") or ""):
        return False
    return True


def _log_action(op: str, args: dict) -> None:
    RECENT_ACTIONS.append({"t": time.time(), "op": op, "args": args})


def _ensure_unitymol() -> UnityMolZMQ:
    global unitymol
    if unitymol is None:
        host = os.environ.get("UMOL_HOST") or "localhost"
        port = int(os.environ.get("UMOL_PORT", "5555"))
        client = UnityMolZMQ(host=host, port=port)
        if not client.connect():
            raise ConnectionError(f"Could not connect to UnityMol ZMQ at {host}:{port}")
        unitymol = client
    return unitymol


def _maybe_normalize(program: str) -> tuple[bool, str, dict]:
    dev = dev_mode_enabled()
    norm, ninfo = normalize_dsl(program, dev=dev)
    return dev, norm, ninfo


def _send_unitymol(command: str, *, log: bool = True) -> tuple[Dict[str, Any], bool]:
    global unitymol
    unitymol = _ensure_unitymol()

    raw = unitymol.send_command(command)
    eff = _effective_success(raw)

    if log:
        _log_action(
            "unitymol.call",
            {
                "command": command,
                "success": eff,
                "raw_success": raw.get("success", False),
                "result": raw.get("result", ""),
            },
        )
    return raw, eff


def _attach_dev(resp: Dict[str, Any], *, dev: bool, ok: bool, ninfo: dict, norm: str) -> None:
    if not dev:
        return
    if ninfo.get("changed") or not ok:
        resp["dev"] = {"normalized_dsl": norm, "normalize_info": ninfo}


def _clean_instance(result_val: Any) -> Optional[str]:
    if result_val is None:
        return None
    s = str(result_val).strip()
    if not s:
        return None
    if _INSTANCE_RE.match(s):
        return s
    return None


def _parse_listish(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]

    s = str(v).strip()
    if not s or s == "[]":
        return []

    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass

    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
        return [p for p in parts if p]

    return [ln.strip() for ln in s.splitlines() if ln.strip()]


async def _poll_load_evidence(timeout_s: float) -> Dict[str, Any]:
    """
    Poll for evidence that a structure is actually loaded.

    Primary signal (most reliable in your UnityMol build):
      - getSelectionListString()

    Secondary signal (often times out in your build):
      - getStructureListString()
    """
    start = time.monotonic()
    last_sel: Optional[Dict[str, Any]] = None
    last_struct: Optional[Dict[str, Any]] = None

    while (time.monotonic() - start) < timeout_s:
        raw_sel, eff_sel = _send_unitymol("getSelectionListString()", log=False)
        last_sel = {"raw": raw_sel, "effective_success": eff_sel}
        if eff_sel:
            sels = _parse_listish(raw_sel.get("result"))
            if sels:
                all_sels = [x for x in sels if x.startswith("all_")]
                return {
                    "ok": True,
                    "source": "getSelectionListString",
                    "selections": sels,
                    "all_selections": all_sels,
                }

        raw_struct, eff_struct = _send_unitymol("getStructureListString()", log=False)
        last_struct = {"raw": raw_struct, "effective_success": eff_struct}
        if eff_struct:
            structs = _parse_listish(raw_struct.get("result"))
            if structs:
                return {"ok": True, "source": "getStructureListString", "structures": structs}

        await asyncio.sleep(POLL_INTERVAL_S)

    return {"ok": False, "last_selection": last_sel, "last_structure": last_struct}


def _rcsb_url(pdb_id: str, fmt: str) -> str:
    pdb = pdb_id.strip().upper()
    f = (fmt or "pdb").strip().lower()
    ext = "pdb" if f == "pdb" else "cif"
    return f"https://files.rcsb.org/download/{pdb}.{ext}"


def _build_loadfromstring_candidates(pdb: str, ext: str, data_text: str) -> List[str]:
    safe = json.dumps(data_text)
    name = f"{pdb}.{ext}"
    return [
        f'loadFromString("{name}", {safe})',
        f'loadFromString("{name}", {safe}, True, False, True, True, True, -1)',
    ]


def _windows_user() -> str:
    """
    Best-effort Windows user name for building a path like:
      C:/Users/<user>/unitymol_data/<pdbid>.pdb
    """
    if WIN_USER:
        return WIN_USER
    # fall back to USER if it exists (often WSL username), still better than empty
    return os.environ.get("USER", "joseph")


def _win_pdb_dir() -> str:
    """
    Directory containing PDB files on Windows.
    Override with UMOL_WIN_PDB_DIR, else default to:
      C:/Users/<WIN_USER>/unitymol_data
    """
    if UMOL_WIN_PDB_DIR:
        return UMOL_WIN_PDB_DIR.rstrip("/").rstrip("\\")
    return f"C:/Users/{_windows_user()}/unitymol_data"


def _default_win_pdb_path(pdb_id: str, fmt: str = "pdb") -> str:
    ext = "pdb" if (fmt or "pdb").strip().lower() == "pdb" else "cif"
    return f"{_win_pdb_dir()}/{pdb_id.strip().lower()}.{ext}"


async def _local_load_structure_internal(pdb_id: str, timeout_s: float, fmt: str) -> dict:
    """
    Try to load via UnityMol `load("<windows-path>")`.
    Returns success only if load evidence appears.
    """
    pdb = (pdb_id or "").strip()
    if not pdb:
        return {"success": False, "stdout": "Empty pdb_id."}

    win_path = _default_win_pdb_path(pdb, fmt=fmt)
    raw_load, eff_load = _send_unitymol(f'load("{win_path}")', log=True)

    # create stable alias (even if evidence lags, the alias name is deterministic)
    alias = f"all_{pdb.lower()}"
    raw_sel, eff_sel = _send_unitymol(f'select("all", "{alias}", True, False, True)', log=True)

    evidence = await _poll_load_evidence(timeout_s)

    ok = bool(eff_load and eff_sel and evidence.get("ok", False))
    return {
        "success": ok,
        "selection_name": alias if ok else None,
        "method": "local_load",
        "path": win_path,
        "load": {
            "command": f'load("{win_path}")',
            "success": eff_load,
            "raw_success": raw_load.get("success", False),
            "result": raw_load.get("result", ""),
            "stdout": raw_load.get("stdout", ""),
        },
        "alias_select": {
            "command": f'select("all", "{alias}", True, False, True)',
            "success": eff_sel,
            "raw_success": raw_sel.get("success", False),
            "result": raw_sel.get("result", ""),
            "stdout": raw_sel.get("stdout", ""),
        },
        "evidence": evidence,
    }


async def _fetch_structure_internal(pdb_id: str, timeout_s: float) -> dict:
    pdb = (pdb_id or "").strip()
    if not pdb:
        return {"success": False, "stdout": "Empty pdb_id."}

    attempts: List[dict] = []
    for use_mmcif in (True, False):
        fetch_cmd = f'fetch("{pdb}", {str(use_mmcif)})'
        raw_fetch, eff_fetch = _send_unitymol(fetch_cmd, log=True)

        # If UnityMol returned an instance, create an instance-based selection too.
        inst = _clean_instance(raw_fetch.get("result"))
        if eff_fetch and inst:
            _send_unitymol(f'select("all", "all_{inst}", True, False, True)', log=True)

        evidence = await _poll_load_evidence(timeout_s)
        attempts.append(
            {
                "command": fetch_cmd,
                "use_mmcif": use_mmcif,
                "success": eff_fetch,
                "raw_success": raw_fetch.get("success", False),
                "result": raw_fetch.get("result", ""),
                "stdout": raw_fetch.get("stdout", ""),
                "evidence": evidence,
            }
        )

        if evidence.get("ok", False):
            # PATCH: always create stable alias all_<requested_pdbid>
            alias = f"all_{pdb.lower()}"
            _send_unitymol(f'select("all", "{alias}", True, False, True)', log=True)

            return {
                "success": True,
                "selection_name": alias,
                "evidence": evidence,
                "fetch": attempts[-1],
                "attempts": attempts,
            }

    return {
        "success": False,
        "stdout": "fetch() returned but no load evidence appeared (no structures/selections).",
        "attempts": attempts,
    }


async def _load_rcsb_internal(pdb_id: str, fmt: str, timeout_s: float) -> dict:
    pdb = (pdb_id or "").strip()
    if not pdb:
        return {"success": False, "stdout": "Empty pdb_id."}

    ff = (fmt or "pdb").strip().lower()
    ff = "pdb" if ff == "pdb" else "cif"
    url = _rcsb_url(pdb, ff)

    try:
        data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "stdout": f"Download failed: {e}", "url": url}

    candidates = _build_loadfromstring_candidates(pdb, ff, data)
    last_try: Optional[dict] = None

    for cmd in candidates:
        raw_load, eff_load = _send_unitymol(cmd, log=True)
        last_try = {
            "command": cmd,
            "success": eff_load,
            "raw_success": raw_load.get("success", False),
            "result": raw_load.get("result", ""),
            "stdout": raw_load.get("stdout", ""),
        }

        inst = _clean_instance(raw_load.get("result"))
        if eff_load and inst:
            _send_unitymol(f'select("all", "all_{inst}", True, False, True)', log=True)

        evidence = await _poll_load_evidence(timeout_s)
        if evidence.get("ok", False):
            # PATCH: always create stable alias all_<requested_pdbid>
            alias = f"all_{pdb.lower()}"
            _send_unitymol(f'select("all", "{alias}", True, False, True)', log=True)
            return {"success": True, "selection_name": alias, "url": url, "load": last_try, "evidence": evidence}

    return {
        "success": False,
        "stdout": "loadFromString ran but no load evidence appeared.",
        "url": url,
        "load": last_try,
        "evidence": await _poll_load_evidence(0.01),
    }


async def _load_structure_internal(pdb_id: str, timeout_s: float, fmt: str) -> dict:
    """
    Robust loader:
      0) local load (Windows path) — best for your environment
      1) fetch()
      2) download+loadFromString()
    """
    # 0) Local load first (your known-good path)
    local = await _local_load_structure_internal(pdb_id, timeout_s=timeout_s, fmt=fmt)
    if local.get("success", False):
        return local

    # 1) fetch()
    first = await _fetch_structure_internal(pdb_id, timeout_s=timeout_s)
    if first.get("success", False):
        first["method"] = "fetch"
        return first

    # 2) RCSB loadFromString()
    fallback = await _load_rcsb_internal(pdb_id, fmt=fmt, timeout_s=timeout_s)
    if fallback.get("success", False):
        fallback["method"] = "rcsb_loadFromString"
        return fallback

    return {
        "success": False,
        "stdout": "All load methods failed: local_load, fetch, load_rcsb.",
        "local_load": local,
        "fetch_structure": first,
        "load_rcsb": fallback,
    }


# -----------------------------
# Step 2 helpers: robust Color
# -----------------------------
def _rgba_from_name(name: str) -> Optional[List[float]]:
    palette = {
        "red": [1.0, 0.0, 0.0, 1.0],
        "green": [0.0, 1.0, 0.0, 1.0],
        "blue": [0.0, 0.0, 1.0, 1.0],
        "white": [1.0, 1.0, 1.0, 1.0],
        "black": [0.0, 0.0, 0.0, 1.0],
        "yellow": [1.0, 1.0, 0.0, 1.0],
        "cyan": [0.0, 1.0, 1.0, 1.0],
        "magenta": [1.0, 0.0, 1.0, 1.0],
        "orange": [1.0, 0.5, 0.0, 1.0],
        "gray": [0.5, 0.5, 0.5, 1.0],
        "grey": [0.5, 0.5, 0.5, 1.0],
        "purple": [0.5, 0.0, 0.5, 1.0],
    }
    return palette.get(name.lower().strip())


def _parse_rgba_listish(s: str) -> Optional[List[float]]:
    t = s.strip().lstrip("[").rstrip("]")
    parts = [p.strip() for p in t.split(",") if p.strip()]
    if len(parts) != 4:
        return None
    try:
        return [float(x) for x in parts]
    except Exception:
        return None


def _unity_color_expr(rgba: List[float]) -> str:
    r, g, b, a = rgba
    return f'__import__("UnityEngine").Color({r:.6f},{g:.6f},{b:.6f},{a:.6f})'


def _color_arg_candidates(color: str) -> List[str]:
    t = (color or "").strip()
    if not t:
        return []

    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        name = t[1:-1].strip().lower()
        out = [f'"{name}"']
        rgba = _rgba_from_name(name)
        if rgba is not None:
            out.append(_unity_color_expr(rgba))
        return out

    rgba = _parse_rgba_listish(t)
    if rgba is not None:
        return [_unity_color_expr(rgba)]

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
        name = t.lower()
        out = [f'"{name}"']
        mapped = _rgba_from_name(name)
        if mapped is not None:
            out.append(_unity_color_expr(mapped))
        return out

    return [t]


def _normalize_rep_type(rep_type: str) -> str:
    t = (rep_type or "").strip().lower()
    mapping = {
        "cartoon": "c",
        "c": "c",
        "hyperball": "hb",
        "hb": "hb",
        "line": "l",
        "lines": "l",
        "l": "l",
        "surface": "s",
        "s": "s",
        "trace": "trace",
        "sphere": "sphere",
        "bondorder": "bondorder",
        "hbond": "hbond",
        "hbondtubes": "hbondtubes",
        "points": "p",
        "p": "p",
    }
    return mapping.get(t, (rep_type or "").strip())


async def _color_selection_internal(selection_name: str, rep_type: str, color: str, *, log_unitymol: bool) -> Dict[str, Any]:
    rep = _normalize_rep_type(rep_type)
    args = _color_arg_candidates(color)

    attempts: List[Dict[str, Any]] = []
    last_raw: Dict[str, Any] = {"success": False, "result": "", "stdout": ""}
    last_eff: bool = False
    used_cmd: str = ""

    for arg in args:
        cmd = f'colorSelection("{selection_name}", "{rep}", {arg})'
        raw, eff = _send_unitymol(cmd, log=log_unitymol)

        attempts.append(
            {
                "command": cmd,
                "arg": arg,
                "success": eff,
                "raw_success": raw.get("success", False),
                "result": raw.get("result", ""),
                "stdout": raw.get("stdout", ""),
            }
        )

        last_raw = raw
        last_eff = eff
        used_cmd = cmd
        if eff:
            break

    combined_stdout = "\n".join(a.get("stdout", "") for a in attempts if a.get("stdout"))
    return {
        "success": last_eff,
        "raw_success": last_raw.get("success", False),
        "result": last_raw.get("result", ""),
        "stdout": combined_stdout,
        "used_command": used_cmd,
        "attempts": attempts,
    }


# -----------------------------
# Step 3: NL -> DSL translation
# -----------------------------
def _http_post_json(url: str, payload: dict, timeout_s: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return {"dsl": "", "meta": {"raw": raw, "parse_error": True}}


def _nl_to_dsl_python(user_text: str, scene_ctx: dict, dev: bool) -> Tuple[str, dict]:
    if not PY_MOD or not PY_FUNC:
        raise RuntimeError("UMOL_NL_PY_MODULE / UMOL_NL_PY_FUNC not set for python backend.")
    mod = importlib.import_module(PY_MOD)
    fn = getattr(mod, PY_FUNC, None)
    if fn is None:
        raise RuntimeError(f"Callable {PY_FUNC} not found in module {PY_MOD}.")
    out = fn(user_text=user_text, scene_context=scene_ctx, dev=dev)
    if isinstance(out, str):
        return out, {"backend": "python", "module": PY_MOD, "func": PY_FUNC}
    if isinstance(out, dict):
        return str(out.get("dsl", "") or ""), {
            "backend": "python",
            "module": PY_MOD,
            "func": PY_FUNC,
            "meta": out.get("meta", {}),
        }
    return "", {"backend": "python", "error": "callable_return_type_invalid"}


def _nl_to_dsl_openai(user_text: str, scene_ctx: dict, dev: bool) -> Tuple[str, dict]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set.")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError(f"openai package not available in this environment: {e}")

    client = OpenAI(api_key=api_key)

    system = (
        "You translate user requests into MolCommand DSL for UnityMol.\n"
        "Rules:\n"
        "- Output ONLY the DSL program (no markdown, no explanation).\n"
        "- Use existing selections when possible (from scene_context).\n"
        "- If user asks to load a PDB ID, emit the DSL load command used by this system.\n"
        "- Prefer stable alias selections all_<pdbid> after loading.\n"
        "- If ambiguous, make the safest assumption consistent with scene_context.\n"
    )

    user_payload = {
        "user_text": user_text,
        "scene_context": scene_ctx,
        "dev": dev,
        "output_spec": "Return ONLY MolCommand DSL as plain text.",
    }

    resp = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        temperature=0.0,
    )

    dsl = ""
    try:
        dsl = (getattr(resp, "output_text", "") or "").strip()
    except Exception:
        dsl = ""

    return dsl, {"backend": "openai", "model": OPENAI_MODEL}


def _nl_to_dsl_internal(user_text: str, scene_ctx: dict, dev: bool) -> Tuple[str, dict]:
    backend = NL_BACKEND
    if not backend:
        backend = "http" if NL_ENDPOINT else ""

    if backend == "http":
        if not NL_ENDPOINT:
            raise RuntimeError("UMOL_NL_ENDPOINT not set for http backend.")
        payload = {"user_text": user_text, "scene_context": scene_ctx, "dev": dev}
        out = _http_post_json(NL_ENDPOINT, payload, timeout_s=30.0)
        dsl = str(out.get("dsl", "") or "").strip()
        return dsl, {"backend": "http", "endpoint": NL_ENDPOINT, "meta": out.get("meta", {})}

    if backend == "openai":
        return _nl_to_dsl_openai(user_text, scene_ctx, dev)

    if backend == "python":
        return _nl_to_dsl_python(user_text, scene_ctx, dev)

    raise RuntimeError(
        "No NL backend configured. Set one of:\n"
        "- UMOL_NL_BACKEND=http + UMOL_NL_ENDPOINT=...\n"
        "- UMOL_NL_BACKEND=openai + OPENAI_API_KEY=...\n"
        "- UMOL_NL_BACKEND=python + UMOL_NL_PY_MODULE + UMOL_NL_PY_FUNC"
    )


# -----------------------------
# Core tools
# -----------------------------
@mcp.tool()
async def execute_unitymol_command(command: str) -> dict:
    """Execute a UnityMol API command and return the result (with effective_success)."""
    try:
        raw, eff = _send_unitymol(command, log=True)
        return {
            "success": eff,
            "raw_success": raw.get("success", False),
            "result": raw.get("result", ""),
            "stdout": raw.get("stdout", ""),
            "command": command,
        }
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return {"success": False, "raw_success": False, "result": "", "stdout": str(e), "command": command}


@mcp.tool()
async def init_unitymol_copilot() -> dict:
    """Explicit initializer (optional). Uses UMOL_HOST/UMOL_PORT if set."""
    global unitymol
    try:
        unitymol = _ensure_unitymol()
    except Exception as e:
        logger.error(f"Failed to connect to UnityMol: {e}")
        return {"success": False, "message": str(e)}
    logger.info("Successfully connected to UnityMol")
    return {"success": True, "message": "Initialized UnityMol Copilot with ZMQ connection"}


@mcp.tool()
async def validate_dsl(program: str) -> dict:
    dev, norm, ninfo = _maybe_normalize(program)
    ok, ast, errors = parse_and_validate_molcommand(norm)
    resp: Dict[str, Any] = {"ok": ok, "ast": ast, "errors": errors}
    _attach_dev(resp, dev=dev, ok=ok, ninfo=ninfo, norm=norm)
    return resp


async def _execute_ast(ast: list[dict[str, Any]]) -> dict:
    _ = _ensure_unitymol()

    commands = dsl_to_zmq_calls(ast)
    outputs: List[Dict[str, Any]] = []
    loads: List[Dict[str, Any]] = []

    for cmd in commands:
        m = _LOAD_DIRECTIVE_RE.match(cmd.strip())
        if m:
            pdb = m.group(1).strip()
            try:
                loaded = await _load_structure_internal(pdb, timeout_s=DEFAULT_LOAD_TIMEOUT_S, fmt="pdb")
            except Exception as e:
                loaded = {"success": False, "stdout": f"Loader crashed: {e}", "selection_name": None}

            ok = bool(loaded.get("success", False))
            sel_name = loaded.get("selection_name")

            _log_action(
                "dsl.load",
                {
                    "pdb_id": pdb,
                    "success": ok,
                    "method": loaded.get("method", ""),
                    "selection_name": sel_name,
                },
            )
            loads.append(
                {
                    "pdb_id": pdb,
                    "success": ok,
                    "method": loaded.get("method", ""),
                    "selection_name": sel_name,
                }
            )

            outputs.append(
                {
                    "command": cmd,
                    "success": ok,
                    "raw_success": ok,
                    "result": sel_name or "",
                    "stdout": loaded.get("stdout", "") or "",
                    "load_details": loaded,
                }
            )
            continue

        mc = _COLOR_DIRECTIVE_RE.match(cmd.strip())
        if mc:
            sel = mc.group(1).strip()
            rep = mc.group(2).strip()
            col = mc.group(3).strip()

            colored = await _color_selection_internal(sel, rep, col, log_unitymol=False)

            _log_action(
                "dsl.exec",
                {
                    "command": colored.get("used_command", ""),
                    "success": bool(colored.get("success", False)),
                    "raw_success": bool(colored.get("raw_success", False)),
                    "result": colored.get("result", ""),
                },
            )

            outputs.append(
                {
                    "command": cmd,
                    "success": bool(colored.get("success", False)),
                    "raw_success": bool(colored.get("success", False)),
                    "result": colored.get("result", ""),
                    "stdout": colored.get("stdout", ""),
                    "used_command": colored.get("used_command", ""),
                    "attempts": colored.get("attempts", []),
                }
            )
            continue

        raw, eff = _send_unitymol(cmd, log=False)
        _log_action(
            "dsl.exec",
            {"command": cmd, "success": eff, "raw_success": raw.get("success", False), "result": raw.get("result", "")},
        )
        outputs.append(
            {"command": cmd, "success": eff, "raw_success": raw.get("success", False), "result": raw.get("result", ""), "stdout": raw.get("stdout", "")}
        )

    success = all(o.get("success", False) for o in outputs)
    last = outputs[-1] if outputs else {}

    return {
        "success": success,
        "result": last.get("result", ""),
        "stdout": "\n".join(o.get("stdout", "") for o in outputs if o.get("stdout")),
        "commands": [o["command"] for o in outputs],
        "raw": outputs,
        "loads": loads,
    }


@mcp.tool()
async def execute_dsl(program: str) -> dict:
    dev, norm, ninfo = _maybe_normalize(program)

    ok, ast, errors = parse_and_validate_molcommand(norm)
    if not ok:
        resp: Dict[str, Any] = {"success": False, "result": "", "stdout": "\n".join(errors), "commands": []}
        _attach_dev(resp, dev=dev, ok=ok, ninfo=ninfo, norm=norm)
        return resp

    try:
        out = await _execute_ast(ast)
        _attach_dev(out, dev=dev, ok=bool(out.get("success", False)), ninfo=ninfo, norm=norm)
        return out
    except Exception as e:
        logger.error(f"execute_dsl error: {e}")
        resp = {"success": False, "result": "", "stdout": str(e), "commands": []}
        _attach_dev(resp, dev=dev, ok=False, ninfo=ninfo, norm=norm)
        return resp


@mcp.tool()
async def execute_nl(user_text: str) -> dict:
    """
    Translate natural language -> MolCommand DSL -> execute.

    Returns:
      {
        "success": bool,
        "dsl": "...",
        "translation": { ...backend meta... },
        "execution": { ...execute_dsl output... },
        "stdout": "..."
      }
    """
    dev = dev_mode_enabled()
    global unitymol
    unitymol = _ensure_unitymol()

    scene_ctx = build_scene_context(unitymol, list(RECENT_ACTIONS), compact=True)

    try:
        dsl, tmeta = _nl_to_dsl_internal(user_text, scene_ctx, dev=dev)
    except Exception as e:
        return {
            "success": False,
            "dsl": "",
            "translation": {"error": str(e), "backend": NL_BACKEND or "auto"},
            "execution": {},
            "stdout": str(e),
        }

    if not dsl.strip():
        return {
            "success": False,
            "dsl": dsl,
            "translation": tmeta,
            "execution": {},
            "stdout": "Translator returned empty DSL.",
        }

    exec_out = await execute_dsl(dsl)

    ok = bool(exec_out.get("success", False))
    stdout = (exec_out.get("stdout", "") or "").strip()

    _log_action("nl.exec", {"user_text": user_text, "dsl": dsl, "success": ok, "backend": tmeta.get("backend", "")})

    return {
        "success": ok,
        "dsl": dsl,
        "translation": tmeta,
        "execution": exec_out,
        "stdout": stdout,
    }


@mcp.tool()
async def fetch_structure(pdb_id: str, timeout_s: float = DEFAULT_LOAD_TIMEOUT_S) -> dict:
    return await _fetch_structure_internal(pdb_id, timeout_s=timeout_s)


@mcp.tool()
async def load_rcsb(pdb_id: str, fmt: str = "pdb", timeout_s: float = DEFAULT_LOAD_TIMEOUT_S) -> dict:
    return await _load_rcsb_internal(pdb_id, fmt=fmt, timeout_s=timeout_s)


@mcp.tool()
async def load_structure(pdb_id: str, timeout_s: float = DEFAULT_LOAD_TIMEOUT_S, fmt: str = "pdb") -> dict:
    return await _load_structure_internal(pdb_id, timeout_s=timeout_s, fmt=fmt)


@mcp.tool()
async def show_representation(selection_name: str, rep_type: str) -> dict:
    rep = _normalize_rep_type(rep_type)
    cmd = f'showSelection("{selection_name}", "{rep}")'
    return await execute_unitymol_command(cmd)


@mcp.tool()
async def hide_selection(selection_name: str) -> dict:
    cmd = f'hideSelection("{selection_name}")'
    return await execute_unitymol_command(cmd)


@mcp.tool()
async def color_selection(selection_name: str, rep_type: str, color: str) -> dict:
    try:
        return await _color_selection_internal(selection_name, rep_type, color, log_unitymol=True)
    except Exception as e:
        return {"success": False, "raw_success": False, "result": "", "stdout": str(e), "command": ""}


@mcp.tool()
async def color_by_chain(selection_name: str, rep_type: str) -> dict:
    rep = _normalize_rep_type(rep_type)
    cmd = f'colorByChain("{selection_name}", "{rep}")'
    return await execute_unitymol_command(cmd)


@mcp.tool()
async def color_by_atom(selection_name: str, rep_type: str) -> dict:
    rep = _normalize_rep_type(rep_type)
    cmd = f'colorByAtom("{selection_name}", "{rep}")'
    return await execute_unitymol_command(cmd)


@mcp.tool()
async def color_by_residue(selection_name: str, rep_type: str) -> dict:
    rep = _normalize_rep_type(rep_type)
    cmd = f'colorByResidue("{selection_name}", "{rep}")'
    return await execute_unitymol_command(cmd)


@mcp.tool()
async def scene_context(compact: bool = True) -> dict:
    global unitymol
    unitymol = _ensure_unitymol()
    ctx = build_scene_context(unitymol, list(RECENT_ACTIONS), compact=compact)
    return {"success": True, "context": ctx}


def main_sync() -> int:
    global unitymol
    try:
        unitymol = _ensure_unitymol()
    except Exception as e:
        logger.error(f"Failed to connect to UnityMol. Is the ZMQ server running on 5555? {e}")
        return 1

    logger.info("UnityMolZMQ ready; FastMCP tools registered.")

    if hasattr(mcp, "run"):
        mcp.run()
    elif hasattr(mcp, "serve"):
        asyncio.run(mcp.serve())
    else:
        raise RuntimeError("FastMCP: no run()/serve() found")

    return 0


if __name__ == "__main__":
    raise SystemExit(main_sync())

