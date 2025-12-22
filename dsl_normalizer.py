#!/usr/bin/env python3
"""
unitymol_copilot.dsl_normalizer

DEV_MODE DSL normalization layer.

Purpose:
- Keep strict DSL grammar unchanged.
- In DEV mode, rewrite a few known "LLM-ish" formats into strict DSL
  BEFORE validation/parsing.

This is intentionally conservative: it only applies transformations that are
unambiguous and already expected in the project.

Key behavior:
- Normalizes *line-by-line* so multi-line programs work.
  (Most LLM slips happen per statement, not across statements.)

Tiers:
- MOLCOMMANDNL_DEV=1:
    conservative normalization only
- MOLCOMMANDNL_DEV_LOOSE=1 (requires DEV=1):
    additionally:
      - split semicolon-separated statements into lines (best-effort)
      - drop non-DSL lines
      - strip list markers
      - strip trailing '.' / ';'
"""

from __future__ import annotations

import os
import re
from typing import Dict, Tuple


_VERBS = ("add_structure", "select", "show", "hide", "color_by_chain")


def dev_mode_enabled() -> bool:
    """Return True iff DEV_MODE is enabled."""
    return os.environ.get("MOLCOMMANDNL_DEV") == "1"


def dev_loose_enabled() -> bool:
    """Return True iff DEV_LOOSE is enabled (only meaningful when DEV is enabled)."""
    return os.environ.get("MOLCOMMANDNL_DEV_LOOSE") == "1"


def normalize_dsl(text: str, *, dev: bool | None = None) -> Tuple[str, Dict]:
    """
    Normalize DSL text.

    Args:
        text: raw DSL-ish string.
        dev: override dev-mode detection. If None, uses env MOLCOMMANDNL_DEV.

    Returns:
        (normalized_text, info_dict)
    """
    if dev is None:
        dev = dev_mode_enabled()

    raw = (text or "").strip()
    info: Dict = {"dev": dev, "changed": False, "steps": []}

    if not raw or not dev:
        return raw, info

    loose = dev_loose_enabled()
    if loose:
        info["steps"].append("dev_loose")

    # Strip fences/prefix first (may produce multi-line DSL).
    s = _strip_code_fences_and_prefix(raw, info)

    # In DEV_LOOSE: split "stmt(...); stmt(...)" into separate lines (best-effort).
    if loose:
        s = _split_semicolons(s, info)

    # In DEV_LOOSE: drop commentary / non-DSL lines (best-effort).
    if loose:
        s = _drop_non_dsl_lines(s, info)

    # Normalize statement-by-statement (line-by-line).
    # This avoids "whole-program" regexes failing on multi-line input.
    lines_in = s.splitlines()
    lines_out = []

    # Reduce step spam (record once per program).
    did_list_marker = False
    did_trailing_punct = False

    for idx, line in enumerate(lines_in, start=1):
        orig_line = line
        stripped = line.strip()

        if not stripped:
            lines_out.append(line)
            continue

        # Preserve indentation (nice for debugging / readability).
        indent = orig_line[: len(orig_line) - len(orig_line.lstrip())]

        t = stripped

        if loose:
            t2 = _strip_leading_list_marker(t)
            if t2 != t:
                if not did_list_marker:
                    info["steps"].append("strip_list_marker")
                    did_list_marker = True
                t = t2

            # Strip trailing punctuation that frequently breaks strict parsing.
            t2 = re.sub(r"[;.\s]+$", "", t)
            if t2 != t:
                if not did_trailing_punct:
                    info["steps"].append("strip_trailing_punct")
                    did_trailing_punct = True
                t = t2

        # Canonicalize call-verb case early (Show(...) -> show(...))
        t = _canonicalize_call_verb(t, info)

        # Convert common non-call forms to strict call syntax.
        t = _normalize_parenthesized_form(t, info)
        t = _normalize_space_arg_form(t, info)

        # Canonicalize again in case conversion produced a call-form with mixed case.
        t = _canonicalize_call_verb(t, info)

        # Fix missing commas in call forms.
        t = _insert_missing_commas(t, info)

        # Repair known single-arg slip.
        t = _normalize_color_by_chain_single_arg(t, info)

        if t != stripped:
            info["steps"].append(f"line:{idx}")

        lines_out.append(indent + t)

    s2 = "\n".join(lines_out)

    if s2 != raw:
        info["changed"] = True
    return s2, info


def _strip_code_fences_and_prefix(s: str, info: Dict) -> str:
    orig = s

    # Drop "DSL>" prefix if present (both whole-string and per-line).
    s = re.sub(r"^\s*DSL>\s*", "", s)
    s = re.sub(r"^\s*DSL>\s*", "", s, flags=re.M)

    # Extract from ``` fences if user/LLM included them.
    m = re.search(r"```(?:\w+)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1).strip()

    if s != orig:
        info["steps"].append("strip_fences/prefix")
    return s


def _split_semicolons(s: str, info: Dict) -> str:
    """
    DEV_LOOSE helper: split semicolon-separated statements into separate lines,
    but only when the semicolon is followed by something that looks like a DSL stmt.
    """
    orig = s
    verbs = "|".join(_VERBS)
    pat = rf";\s*(?=(?:[-*]\s*|\d+\s*[.)]\s*)?\(?\s*(?:{verbs})\b)"
    s2 = re.sub(pat, "\n", s, flags=re.I)
    if s2 != orig:
        info["steps"].append("split_semicolons")
    return s2


def _strip_leading_list_marker(s: str) -> str:
    """
    Remove common bullet/numbering prefixes:

      "- show(...)"
      "* show(...)"
      "1) show(...)"
      "2. show(...)"

    Also tolerates no space after marker (e.g., "-show(...)", "1)show(...)").
    """
    return re.sub(r"^\s*(?:[-*]\s*|\d+\s*[.)]\s*)", "", s)


def _looks_like_dsl_stmt(line: str) -> bool:
    t = line.strip()
    if not t:
        return False

    # Allow list markers in loose mode input; remove them for detection.
    t = _strip_leading_list_marker(t)

    # allow "(show ...)" and "show ..." and "show(...)" forms
    verbs = "|".join(_VERBS)
    return bool(re.match(rf"^\(?\s*({verbs})\b", t, flags=re.I))


def _drop_non_dsl_lines(s: str, info: Dict) -> str:
    """
    DEV_LOOSE helper: retain only lines that look like DSL statements.
    If this would drop everything, keep original.
    """
    orig = s
    keep = []
    dropped = 0

    for line in s.splitlines():
        if _looks_like_dsl_stmt(line):
            keep.append(line)
        else:
            if line.strip():
                dropped += 1

    if dropped:
        info["steps"].append(f"drop_non_dsl:{dropped}")

    if keep:
        out = "\n".join(keep)
        return out if out != orig else orig

    return orig


def _canonicalize_call_verb(s: str, info: Dict) -> str:
    """
    Canonicalize verb case in call-form statements:

      Show(sel="x", rep="y") -> show(sel="x", rep="y")
    """
    orig = s
    m = re.match(r"^([A-Za-z_]\w*)\s*\(", s)
    if not m:
        return s

    fn_raw = m.group(1)
    fn = fn_raw.lower()
    if fn in _VERBS and fn_raw != fn:
        s = fn + s[len(fn_raw) :]
        info["steps"].append("verb_lowercase_call")

    return s if s != orig else orig


def _normalize_parenthesized_form(s: str, info: Dict) -> str:
    """
    (show sel=".." rep="..") -> show(sel="..", rep="..")

    Also canonicalizes verb to lowercase (Show -> show) for strict parsing.
    """
    orig = s
    m = re.match(r"^\(\s*([A-Za-z_]\w*)\s+(.*)\)\s*$", s, flags=re.S)
    if m:
        fn_raw, inner = m.group(1), m.group(2).strip()
        fn = fn_raw.lower()
        if fn in _VERBS:
            # Add commas when args are space-separated.
            inner = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', inner)
            s = f"{fn}({inner})"

    if s != orig:
        info["steps"].append("paren_form")
    return s


def _normalize_space_arg_form(s: str, info: Dict) -> str:
    """
    show sel=".." rep=".." -> show(sel="..", rep="..")

    Also canonicalizes verb to lowercase for strict parsing.
    """
    orig = s

    # If it already looks like a call, this specific rewrite doesn't apply.
    # (Comma insertion is handled by _insert_missing_commas.)
    if "(" in s:
        return s

    m = re.match(r"^([A-Za-z_]\w*)\s+(.+)$", s, flags=re.S)
    if m:
        fn_raw, inner = m.group(1), m.group(2).strip()
        fn = fn_raw.lower()
        if fn in _VERBS and "=" in inner:
            inner = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', inner)
            s = f"{fn}({inner})"

    if s != orig:
        info["steps"].append("space_args")
    return s


def _insert_missing_commas(s: str, info: Dict) -> str:
    """
    show(sel="x" rep="y") -> show(sel="x", rep="y")
    """
    orig = s
    s2 = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', s)
    if s2 != orig:
        info["steps"].append("insert_commas")
    return s2


def _normalize_color_by_chain_single_arg(s: str, info: Dict) -> str:
    """
    color_by_chain(sel="all_cartoon") -> color_by_chain(sel="all", target="cartoon")
    color_by_chain(sel="cartoon")     -> color_by_chain(sel="all", target="cartoon")

    NOTE: We intentionally default sel="all" here; your REPL can rewrite sel="all"
    to last_all_sel (all_<code>) for execution correctness.
    """
    orig = s

    m = re.fullmatch(r'color_by_chain\(\s*sel\s*=\s*"([^"]+)"\s*\)\s*', s)
    if not m:
        return s

    raw_sel = m.group(1).strip().lower()
    reps = ("cartoon", "lines", "spheres", "surface")

    target = None
    if raw_sel in reps:
        target = raw_sel
    elif raw_sel.startswith("all_") and raw_sel[4:] in reps:
        target = raw_sel[4:]

    if target:
        s = f'color_by_chain(sel="all", target="{target}")'
        info["steps"].append("color_by_chain_infer_target")

    return s if s != orig else orig

