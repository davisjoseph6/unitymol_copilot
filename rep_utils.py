#!/usr/bin/env python3
"""rep_utils

Canonicalize reps and convert to UnityMol representation codes using config.

This removes hardcoded mappings like cartoon->"c" from Python code.
"""

from __future__ import annotations

from typing import Optional

from config_loader import load_config

_CFG = load_config()


def canon_rep(rep: Optional[str]) -> Optional[str]:
    """Normalize rep aliases into canonical rep tokens."""
    if rep is None:
        return None
    rep_l = rep.strip().lower()
    aliases = _CFG.synonyms.get("rep_aliases", {}) or {}
    return (aliases.get(rep_l) or rep_l).strip().lower()


def umol_rep_code(rep: Optional[str]) -> Optional[str]:
    """Convert canonical rep token into UnityMol repType code/string."""
    canon = canon_rep(rep)
    if canon is None:
        return None
    codes = _CFG.synonyms.get("umol_rep_codes", {}) or {}
    return codes.get(canon, canon)
