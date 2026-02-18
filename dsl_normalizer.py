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

Config integration:
- config/dsl_registry.json:
    - functions: used to detect valid DSL verbs
    - enums.rep, enums.color_by_chain_targets: used to normalize targets safely
- config/rewrite_rules.yaml:
    - reject_if_matches: patterns that hard-fail
    - repairs: conservative regex repairs
    - alias_verbs: verbs allowed to appear in DEV_LOOSE statement detection
- config/synonyms.yaml:
    - rep_aliases / color_aliases (elsewhere)
    - color_target_aliases: target alias mapping for color_by_chain normalization
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple

from registry_utils import color_by_chain_targets, dsl_verbs, target_aliases


# Optional config integration (for reject/repairs)
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

        # Rewrite alias verbs like add_coloring(...) / colorByChain(...)
        t = _rewrite_color_by_chain_alias_verbs(t, info)

        # Normalize targets/plurals (config-driven)
        t = _normalize_color_by_chain_target_aliases(t, info)

        # Fix sel="all_lines"/etc when target is present
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
    """Fail-fast on forbidden patterns from config/rewrite_rules.yaml."""
    if _CFG is None:
        return
    rules = getattr(_CFG, "rewrite_rules", {}) or {}
    reject = rules.get("reject_if_matches", []) or []
    for pat in reject:
        if re.search(pat, s):
            info["steps"].append("cfg_reject")
            raise ValueError(f"Rejected DSL (matches forbidden pattern): {pat}")


def _cfg_repair_line(line: str, info: Dict[str, Any]) -> str:
    """Apply conservative, config-driven repairs on a single line."""
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
    verbs = dsl_verbs()
    if not verbs:
        return s
    verbs_re = "|".join(re.escape(v) for v in verbs)
    pat = rf";\s*(?=(?:[-*]\s*|\d+\s*[.)]\s*)?\(?\s*(?:{verbs_re})\b)"
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

    verbs = dsl_verbs()
    if not verbs:
        # config missing: be conservative, only keep obvious call-like lines
        return bool(re.match(r"^\(?\s*[A-Za-z_]\w*\s*\(", t))

    verbs_re = "|".join(re.escape(v) for v in verbs)
    return bool(re.match(rf"^\(?\s*(?:{verbs_re})\b", t, flags=re.I))


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
    verbs = set(dsl_verbs()) | set(dsl_verbs())  # cached anyway
    if verbs and fn in verbs and fn_raw.lower() != fn_raw:
        s = fn + s[len(fn_raw) :]
        info["steps"].append("verb_lowercase_call")

    return s if s != orig else orig


def _normalize_parenthesized_form(s: str, info: Dict[str, Any]) -> str:
    orig = s
    m = re.match(r"^\(\s*([A-Za-z_]\w*)\s+(.*)\)\s*$", s, flags=re.S)
    if m:
        fn_raw, inner = m.group(1), m.group(2).strip()
        fn = fn_raw.lower()
        if fn in set(dsl_verbs()):
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
        if fn in set(dsl_verbs()) and "=" in inner:
            inner = re.sub(r'"\s+([A-Za-z_]\w*\s*=)', r'", \1', inner)
            s = f"{fn}({inner})"

    if s != orig:
        info["steps"].append("space_args")
    return s


def _fix_double_quoted_value(s: str, info: Dict[str, Any]) -> str:
    """Fix LLM slip: target=""surface" -> target="surface" (and similar for sel)."""
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
    """
    orig = s
    t = s.strip()

    aliases = set(target_aliases().keys())  # not used; kept for clarity

    # Handle colorByChain / colorbychain specially (positional form).
    if re.fullmatch(r"colorbychain\(\s*(.*?)\s*\)\s*", t, flags=re.I | re.S):
        inner = re.fullmatch(r"colorbychain\(\s*(.*?)\s*\)\s*", t, flags=re.I | re.S).group(1).strip()

        mpos = re.fullmatch(r'"([^"]+)"\s*,\s*"([^"]+)"', inner)
        if mpos:
            sel, target = mpos.group(1), mpos.group(2)
            s2 = f'color_by_chain(sel="{sel}", target="{target}")'
            info["steps"].append("rewrite_color_alias_verb")
            return s2

        sel_m = re.search(r'sel\s*=\s*"([^"]+)"', inner)
        tgt_m = re.search(r'target\s*=\s*"([^"]+)"', inner) or re.search(r'rep\s*=\s*"([^"]+)"', inner)

        sel = sel_m.group(1) if sel_m else None
        target = tgt_m.group(1) if tgt_m else None

        if target and not sel:
            info["steps"].append("rewrite_color_alias_verb")
            return f'color_by_chain(sel="all", target="{target}")'
        if sel and not target:
            info["steps"].append("rewrite_color_alias_verb")
            return f'color_by_chain(sel="{sel}")'
        if sel and target:
            info["steps"].append("rewrite_color_alias_verb")
            return f'color_by_chain(sel="{sel}", target="{target}")'

        return s

    # Config-driven alias verbs (non-camelcase)
    # We only rewrite the known "color-by-chain style" aliases; keep the list in config.
    cfg_aliases = []
    if _CFG is not None:
        rules = getattr(_CFG, "rewrite_rules", {}) or {}
        cfg_aliases = [str(x).strip().lower() for x in (rules.get("alias_verbs", []) or [])]

    known = [a for a in cfg_aliases if a in {"add_coloring", "add_color_command", "add_color_by_chain"}]
    if not known:
        return s

    pat = "|".join(re.escape(v) for v in known)
    m = re.fullmatch(rf"({pat})\(\s*(.*?)\s*\)\s*", t, flags=re.I | re.S)
    if not m:
        return s

    inner = m.group(2).strip()

    sel_m = re.search(r'sel\s*=\s*"([^"]+)"', inner)
    tgt_m = re.search(r'target\s*=\s*"([^"]+)"', inner) or re.search(r'rep\s*=\s*"([^"]+)"', inner)

    if not (sel_m or tgt_m):
        m2 = re.fullmatch(r'"([^"]+)"\s*,\s*"([^"]+)"', inner)
        if m2:
            sel, target = m2.group(1), m2.group(2)
            info["steps"].append("rewrite_color_alias_verb")
            return f'color_by_chain(sel="{sel}", target="{target}")'
        return s

    sel = sel_m.group(1) if sel_m else None
    target = tgt_m.group(1) if tgt_m else None

    if target and not sel:
        info["steps"].append("rewrite_color_alias_verb")
        return f'color_by_chain(sel="all", target="{target}")'
    if sel and not target:
        info["steps"].append("rewrite_color_alias_verb")
        return f'color_by_chain(sel="{sel}")'
    if sel and target:
        info["steps"].append("rewrite_color_alias_verb")
        return f'color_by_chain(sel="{sel}", target="{target}")'

    return s if s == orig else s


def _normalize_color_by_chain_target_aliases(s: str, info: Dict[str, Any]) -> str:
    """Normalize alias targets in color_by_chain calls using config mapping."""
    if not s.lower().startswith("color_by_chain("):
        return s

    orig = s
    m = re.search(r'target\s*=\s*"([^"]+)"', s)
    if not m:
        return s

    aliases = target_aliases()
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
    Fix slip where sel accidentally becomes a representation-like token,
    but only when target is present and sel is NOT a real structure selection.
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

    # Legit structure selection (all_<pdbid>) must remain untouched.
    if re.fullmatch(r"all_[0-9a-z]{4}", sel_l):
        return s

    aliases = target_aliases()
    targets = color_by_chain_targets()

    candidate = sel_l
    if candidate.startswith("all_"):
        candidate = candidate[4:]
    candidate = aliases.get(candidate, candidate)

    if targets and candidate not in targets:
        return s

    s2 = re.sub(r'sel\s*=\s*"([^"]+)"', 'sel="all"', s)
    if s2 != orig:
        info["steps"].append("color_by_chain_sel_repname")
    return s2


def _normalize_color_by_chain_single_arg(s: str, info: Dict[str, Any]) -> str:
    """Infer target from sel when color_by_chain has only sel=... (config-driven)."""
    orig = s
    m = re.fullmatch(r'color_by_chain\(\s*sel\s*=\s*"([^"]+)"\s*\)\s*', s)
    if not m:
        return s

    raw = m.group(1).strip().lower()
    aliases = target_aliases()
    targets = color_by_chain_targets()

    candidate = raw[4:] if raw.startswith("all_") else raw
    candidate = aliases.get(candidate, candidate)

    if targets and candidate not in targets:
        return s

    s2 = f'color_by_chain(sel="all", target="{candidate}")'
    if s2 != orig:
        info["steps"].append("color_by_chain_infer_target")
    return s2
