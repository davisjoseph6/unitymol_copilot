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

Config integration (if present):
- config/rewrite_rules.yaml:
    - reject_if_matches: list of regex patterns that should hard-fail
    - repairs: list of {match, replace_with, note} conservative repairs
- config/synonyms.yaml:
    - rep_aliases: mapping of plural/aliases for representation targets
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple


# Include known "LLM-ish" alias verbs here so DEV_LOOSE doesn't drop them.
# We'll rewrite them back to strict verbs later.
_VERBS = (
    # Core MolCommandNL / UnityMol verbs
    "add_structure",
    "select",
    "show",
    "hide",
    "color_by_chain",
    "update_representation",
    "update_coloring",
    "center",
    "rotate",
    "annotate",
    "measure",
    # alias verbs observed from the model:
    "add_coloring",
    "add_color_command",
    "add_color_by_chain",
    # camelCase alias sometimes used:
    "colorbychain",
)

# Stable, strict targets used by validator/executor.
# Keep this list stable and conservative.
_COLOR_TARGETS = {"atom", "bond", "cartoon", "line", "point", "surface", "tube"}

# Local fallback aliases (used if config is absent).
_FALLBACK_COLOR_TARGET_ALIASES = {
    "atoms": "atom",
    "bonds": "bond",
    "lines": "line",
    "points": "point",
    "tubes": "tube",
    "surfaces": "surface",
    "cartoons": "cartoon",
}


# Optional config integration
try:
    from config_loader import load_config  # type: ignore

    _CFG = load_config()
except Exception:  # pragma: no cover
    _CFG = None


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
    info: Dict[str, Any] = {"dev": dev, "changed": False, "steps": []}

    if not raw or not dev:
        return raw, info

    loose = dev_loose_enabled()
    if loose:
        info["steps"].append("dev_loose")

    s = _strip_code_fences_and_prefix(raw, info)

    # Config-driven hard rejects (fail-fast)
    _cfg_reject(s, info)

    if loose:
        s = _split_semicolons(s, info)
        s = _drop_non_dsl_lines(s, info)

    lines_in = s.splitlines()
    lines_out = []

    did_list_marker = False
    did_trailing_punct = False

    for idx, line in enumerate(lines_in, start=1):
        orig_line = line
        stripped = line.strip()

        if not stripped:
            lines_out.append(line)
            continue

        indent = orig_line[: len(orig_line) - len(orig_line.lstrip())]
        t = stripped

        if loose:
            t2 = _strip_leading_list_marker(t)
            if t2 != t:
                if not did_list_marker:
                    info["steps"].append("strip_list_marker")
                    did_list_marker = True
                t = t2

            t2 = re.sub(r"[;.\s]+$", "", t)
            if t2 != t:
                if not did_trailing_punct:
                    info["steps"].append("strip_trailing_punct")
                    did_trailing_punct = True
                t = t2

        # Config-driven conservative repairs (line-level)
        t = _cfg_repair_line(t, info)

        t = _canonicalize_call_verb(t, info)
        t = _normalize_parenthesized_form(t, info)
        t = _normalize_space_arg_form(t, info)
        t = _canonicalize_call_verb(t, info)

        t = _fix_double_quoted_value(t, info)
        t = _insert_missing_commas(t, info)

        # Rewrite alias verbs like add_coloring(...) / add_color_command(...) / colorByChain(...)
        t = _rewrite_color_by_chain_alias_verbs(t, info)

        # Normalize targets/plurals (config-driven if possible)
        t = _normalize_color_by_chain_target_aliases(t, info)

        # Fix sel="all_lines"/"all_surface"/"all_tube"/etc (rep-like sel) when target is present
        t = _normalize_color_by_chain_sel_repname(t, info)

        # Infer missing target if model encoded it in sel (single-arg form)
        t = _normalize_color_by_chain_single_arg(t, info)

        if t != stripped:
            info["steps"].append(f"line:{idx}")

        lines_out.append(indent + t)

    s2 = "\n".join(lines_out)

    if s2 != raw:
        info["changed"] = True
    return s2, info


def _cfg_reject(s: str, info: Dict[str, Any]) -> None:
    """
    Fail-fast on forbidden patterns from config/rewrite_rules.yaml.

    This prevents unsafe / unsupported DSL from silently slipping through.
    """
    if _CFG is None:
        return
    rules = getattr(_CFG, "rewrite_rules", {}) or {}
    reject = rules.get("reject_if_matches", []) or []
    for pat in reject:
        if re.search(pat, s):
            info["steps"].append("cfg_reject")
            raise ValueError(f"Rejected DSL (matches forbidden pattern): {pat}")


def _cfg_repair_line(line: str, info: Dict[str, Any]) -> str:
    """
    Apply conservative, config-driven repairs on a single line.

    Each repair is applied only if its regex matches the whole line (or is
    sufficiently anchored by the author). Repairs are intended to be safe.
    """
    if _CFG is None:
        return line
    rules = getattr(_CFG, "rewrite_rules", {}) or {}
    repairs = rules.get("repairs", []) or []
    t = line.strip()
    for rule in repairs:
        match = rule.get("match", "")
        replace_with = rule.get("replace_with", "")
        if not match or not replace_with:
            continue
        m = re.match(match, t)
        if not m:
            continue
        try:
            t2 = replace_with.format(**m.groupdict())
        except Exception:
            continue
        if t2 != t:
            info["steps"].append("cfg_repair")
            return t2
    return line


def _strip_code_fences_and_prefix(s: str, info: Dict[str, Any]) -> str:
    orig = s
    s = re.sub(r"^\s*DSL>\s*", "", s)
    s = re.sub(r"^\s*DSL>\s*", "", s, flags=re.M)

    m = re.search(r"```(?:\w+)?\s*(.*?)\s*```", s, flags=re.S)
    if m:
        s = m.group(1).strip()

    if s != orig:
        info["steps"].append("strip_fences/prefix")
    return s


def _split_semicolons(s: str, info: Dict[str, Any]) -> str:
    orig = s
    verbs = "|".join(_VERBS)
    pat = rf";\s*(?=(?:[-*]\s*|\d+\s*[.)]\s*)?\(?\s*(?:{verbs})\b)"
    s2 = re.sub(pat, "\n", s, flags=re.I)
    if s2 != orig:
        info["steps"].append("split_semicolons")
    return s2


def _strip_leading_list_marker(s: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s*|\d+\s*[.)]\s*)", "", s)


def _looks_like_dsl_stmt(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    t = _strip_leading_list_marker(t)
    verbs = "|".join(_VERBS)
    return bool(re.match(rf"^\(?\s*({verbs})\b", t, flags=re.I))


def _drop_non_dsl_lines(s: str, info: Dict[str, Any]) -> str:
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


def _canonicalize_call_verb(s: str, info: Dict[str, Any]) -> str:
    orig = s
    m = re.match(r"^([A-Za-z_]\w*)\s*\(", s)
    if not m:
        return s

    fn_raw = m.group(1)
    fn = fn_raw.lower()
    if fn in _VERBS and fn_raw.lower() != fn_raw:
        # Only record when we actually changed case
        s = fn + s[len(fn_raw) :]
        info["steps"].append("verb_lowercase_call")

    return s if s != orig else orig


def _normalize_parenthesized_form(s: str, info: Dict[str, Any]) -> str:
    orig = s
    m = re.match(r"^\(\s*([A-Za-z_]\w*)\s+(.*)\)\s*$", s, flags=re.S)
    if m:
        fn_raw, inner = m.group(1), m.group(2).strip()
        fn = fn_raw.lower()
        if fn in _VERBS:
            inner = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', inner)
            s = f"{fn}({inner})"

    if s != orig:
        info["steps"].append("paren_form")
    return s


def _normalize_space_arg_form(s: str, info: Dict[str, Any]) -> str:
    orig = s
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


def _fix_double_quoted_value(s: str, info: Dict[str, Any]) -> str:
    """
    Fix LLM slip:
      target=""surface"  -> target="surface"
      target="surface""  -> target="surface"
    Conservative: only touches sel= / target=.
    """
    orig = s
    s2 = re.sub(r'(target|sel)\s*=\s*""([^"]+)"', r'\1="\2"', s)
    s2 = re.sub(r'(target|sel)\s*=\s*"([^"]+)""', r'\1="\2"', s2)
    if s2 != orig:
        info["steps"].append("fix_double_quotes")
    return s2


def _insert_missing_commas(s: str, info: Dict[str, Any]) -> str:
    orig = s
    s2 = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', s)
    if s2 != orig:
        info["steps"].append("insert_commas")
    return s2


def _rewrite_color_by_chain_alias_verbs(s: str, info: Dict[str, Any]) -> str:
    """
    Rewrite known alias verbs into strict DSL:

      add_coloring(target="tube", sel="all")      -> color_by_chain(sel="all", target="tube")
      add_color_command(target="atom", sel="all") -> color_by_chain(sel="all", target="atom")
      add_color_by_chain(target="line", sel="x")  -> color_by_chain(sel="x", target="line")
      colorByChain("all_1crn", "surface")         -> color_by_chain(sel="all_1crn", target="surface")
      colorByChain(sel="all_1crn", target="surface") -> color_by_chain(sel="all_1crn", target="surface")

    Conservative handling:
      - If only target is present -> default sel="all"
      - If only sel is present    -> emit color_by_chain(sel="...") (single-arg inference may kick in)
    """
    orig = s
    t = s.strip()

    # --- camelCase: colorByChain(...) ---
    m = re.fullmatch(r"colorbychain\(\s*(.*?)\s*\)\s*", t, flags=re.I | re.S)
    if m:
        inner = m.group(1).strip()

        # positional: "SEL","TARGET"
        mpos = re.fullmatch(r'"([^"]+)"\s*,\s*"([^"]+)"', inner)
        if mpos:
            sel, target = mpos.group(1), mpos.group(2)
            s2 = f'color_by_chain(sel="{sel}", target="{target}")'
            if s2 != orig:
                info["steps"].append("rewrite_color_alias_verb")
            return s2

        # kwargs: sel="...", target="..." (or rep="...")
        sel_m = re.search(r'sel\s*=\s*"([^"]+)"', inner)
        tgt_m = re.search(r'target\s*=\s*"([^"]+)"', inner)
        if not tgt_m:
            tgt_m = re.search(r'rep\s*=\s*"([^"]+)"', inner)

        sel = sel_m.group(1) if sel_m else None
        target = tgt_m.group(1) if tgt_m else None

        if target and not sel:
            s2 = f'color_by_chain(sel="all", target="{target}")'
            info["steps"].append("rewrite_color_alias_verb")
            return s2
        if sel and not target:
            s2 = f'color_by_chain(sel="{sel}")'
            info["steps"].append("rewrite_color_alias_verb")
            return s2
        if sel and target:
            s2 = f'color_by_chain(sel="{sel}", target="{target}")'
            info["steps"].append("rewrite_color_alias_verb")
            return s2

        return s

    # --- alias verbs with kw-args or positional args ---
    m = re.fullmatch(
        r"(add_coloring|add_color_command|add_color_by_chain)\(\s*(.*?)\s*\)\s*",
        t,
        flags=re.I | re.S,
    )
    if not m:
        return s

    inner = m.group(2).strip()

    # Try kwargs first
    sel_m = re.search(r'sel\s*=\s*"([^"]+)"', inner)
    tgt_m = re.search(r'target\s*=\s*"([^"]+)"', inner)
    if not tgt_m:
        tgt_m = re.search(r'rep\s*=\s*"([^"]+)"', inner)

    # positional: "SEL","TARGET"
    if not (sel_m or tgt_m):
        m2 = re.fullmatch(r'"([^"]+)"\s*,\s*"([^"]+)"', inner)
        if m2:
            sel, target = m2.group(1), m2.group(2)
            s2 = f'color_by_chain(sel="{sel}", target="{target}")'
            info["steps"].append("rewrite_color_alias_verb")
            return s2
        return s

    sel = sel_m.group(1) if sel_m else None
    target = tgt_m.group(1) if tgt_m else None

    if target and not sel:
        s2 = f'color_by_chain(sel="all", target="{target}")'
        info["steps"].append("rewrite_color_alias_verb")
        return s2

    if sel and not target:
        s2 = f'color_by_chain(sel="{sel}")'
        info["steps"].append("rewrite_color_alias_verb")
        return s2

    if sel and target:
        s2 = f'color_by_chain(sel="{sel}", target="{target}")'
        info["steps"].append("rewrite_color_alias_verb")
        return s2

    return s


def _get_target_aliases() -> Dict[str, str]:
    """
    Return target alias mapping, preferring config/synonyms.yaml if available.

    We treat representation aliases as target aliases for color_by_chain.
    """
    if _CFG is None:
        return dict(_FALLBACK_COLOR_TARGET_ALIASES)

    syn = getattr(_CFG, "synonyms", {}) or {}

    # If you later add a dedicated mapping (e.g., color_target_aliases), it will be used.
    dedicated = syn.get("color_target_aliases")
    if isinstance(dedicated, dict) and dedicated:
        return {str(k).lower(): str(v).lower() for k, v in dedicated.items()}

    rep_aliases = syn.get("rep_aliases")
    if isinstance(rep_aliases, dict) and rep_aliases:
        return {str(k).lower(): str(v).lower() for k, v in rep_aliases.items()}

    return dict(_FALLBACK_COLOR_TARGET_ALIASES)


def _normalize_color_by_chain_target_aliases(s: str, info: Dict[str, Any]) -> str:
    """
    Normalize plural/alias targets in color_by_chain calls:
      target="atoms" -> target="atom"
      target="lines" -> target="line"
    """
    if not s.lower().startswith("color_by_chain("):
        return s

    orig = s
    m = re.search(r'target\s*=\s*"([^"]+)"', s)
    if not m:
        return s

    aliases = _get_target_aliases()
    tgt = m.group(1).strip().lower()
    tgt2 = aliases.get(tgt, tgt)
    if tgt2 == tgt:
        return s

    s2 = re.sub(r'target\s*=\s*"([^"]+)"', f'target="{tgt2}"', s)
    if s2 != orig:
        info["steps"].append("target_alias")
    return s2


def _normalize_color_by_chain_sel_repname(s: str, info: Dict[str, Any]) -> str:
    """
    Fix common slip where sel accidentally becomes a representation-like token:

      color_by_chain(sel="all_lines", target="line")      -> color_by_chain(sel="all", target="line")
      color_by_chain(sel="all_surface", target="surface") -> color_by_chain(sel="all", target="surface")
      color_by_chain(sel="lines", target="line")          -> color_by_chain(sel="all", target="line")
      color_by_chain(sel="atoms", target="atom")          -> color_by_chain(sel="all", target="atom")

    IMPORTANT:
    - We only do this when target is present.
    - We do NOT touch sel="all_1crn" (true structure selection).
    """
    if not s.lower().startswith("color_by_chain("):
        return s

    orig = s

    m_sel = re.search(r'sel\s*=\s*"([^"]+)"', s)
    m_tgt = re.search(r'target\s*=\s*"([^"]+)"', s)
    if not (m_sel and m_tgt):
        return s

    sel_raw = m_sel.group(1).strip()
    sel_l = sel_raw.lower()

    # If it's a legit structure selection (all_<4chars>), keep it.
    if re.fullmatch(r"all_[0-9a-z]{4}", sel_l):
        return s

    aliases = _get_target_aliases()

    # Normalize possible "all_<rep>" patterns and bare rep tokens.
    candidate = sel_l
    if candidate.startswith("all_"):
        candidate = candidate[4:]
    candidate = aliases.get(candidate, candidate)

    if candidate not in _COLOR_TARGETS:
        return s

    # Rewrite sel -> "all"
    s2 = re.sub(r'sel\s*=\s*"([^"]+)"', 'sel="all"', s)
    if s2 != orig:
        info["steps"].append("color_by_chain_sel_repname")
    return s2


def _normalize_color_by_chain_single_arg(s: str, info: Dict[str, Any]) -> str:
    """
    If the model encodes the target in sel (single-arg form), infer target:

      color_by_chain(sel="all_cartoon") -> color_by_chain(sel="all", target="cartoon")
      color_by_chain(sel="cartoon")     -> color_by_chain(sel="all", target="cartoon")
      color_by_chain(sel="all_lines")   -> color_by_chain(sel="all", target="line")
      color_by_chain(sel="all_tube")    -> color_by_chain(sel="all", target="tube")

    NOTE: We intentionally default sel="all" here; your REPL rewrites sel="all"
    to last_all_sel (all_<code>) for execution correctness.
    """
    orig = s
    m = re.fullmatch(r'color_by_chain\(\s*sel\s*=\s*"([^"]+)"\s*\)\s*', s)
    if not m:
        return s

    raw = m.group(1).strip().lower()
    aliases = _get_target_aliases()

    candidate = raw[4:] if raw.startswith("all_") else raw
    candidate = aliases.get(candidate, candidate)

    if candidate not in _COLOR_TARGETS:
        return s

    s2 = f'color_by_chain(sel="all", target="{candidate}")'
    if s2 != orig:
        info["steps"].append("color_by_chain_infer_target")
    return s2

