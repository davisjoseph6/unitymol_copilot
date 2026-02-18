#!/usr/bin/env python3
"""registry_utils

Config/registry-derived helpers to avoid hardcoded rule islands.

This file is the single source for:
- DSL verb names (strict + alias verbs)
- Allowed reps
- Allowed color_by_chain targets
- Target alias mapping
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Iterable, List, Set, Tuple

try:
    from config_loader import load_config  # type: ignore
except Exception:  # pragma: no cover
    load_config = None  # type: ignore


def _cfg():
    """Load config if available; return None if config loader isn't usable."""
    if load_config is None:
        return None
    try:
        return load_config()
    except Exception:
        return None


def _lower_list(xs: Iterable) -> List[str]:
    return [str(x).strip().lower() for x in xs if str(x).strip()]


@lru_cache(maxsize=1)
def dsl_function_names() -> Tuple[str, ...]:
    """Strict DSL function names from dsl_registry.json."""
    cfg = _cfg()
    if cfg is None:
        return tuple()
    funcs = (cfg.dsl_registry or {}).get("functions", {}) or {}
    return tuple(sorted(_lower_list(funcs.keys())))


@lru_cache(maxsize=1)
def alias_verbs() -> Tuple[str, ...]:
    """Alias verbs allowed to appear in DEV_LOOSE (from rewrite_rules.yaml)."""
    cfg = _cfg()
    if cfg is None:
        return tuple()
    rules = getattr(cfg, "rewrite_rules", {}) or {}
    aliases = rules.get("alias_verbs", []) or []
    return tuple(sorted(_lower_list(aliases)))


@lru_cache(maxsize=1)
def dsl_verbs() -> Tuple[str, ...]:
    """All verbs recognized by DEV normalizer statement detection."""
    core = set(dsl_function_names())
    aliases = set(alias_verbs())
    return tuple(sorted(core | aliases))


@lru_cache(maxsize=1)
def allowed_reps() -> Set[str]:
    """Allowed rep tokens (from registry enums)."""
    cfg = _cfg()
    if cfg is None:
        return set()
    enums = (cfg.dsl_registry or {}).get("enums", {}) or {}
    reps = enums.get("rep", []) or []
    return set(_lower_list(reps))


@lru_cache(maxsize=1)
def color_by_chain_targets() -> Set[str]:
    """Allowed color_by_chain targets (from registry enums)."""
    cfg = _cfg()
    if cfg is None:
        return set()
    enums = (cfg.dsl_registry or {}).get("enums", {}) or {}
    tgts = enums.get("color_by_chain_targets", []) or []
    return set(_lower_list(tgts))


@lru_cache(maxsize=1)
def target_aliases() -> Dict[str, str]:
    """Alias map for color_by_chain targets; config-first."""
    cfg = _cfg()
    if cfg is None:
        return {}

    syn = getattr(cfg, "synonyms", {}) or {}

    dedicated = syn.get("color_target_aliases")
    if isinstance(dedicated, dict) and dedicated:
        return {str(k).strip().lower(): str(v).strip().lower() for k, v in dedicated.items()}

    # fallback to rep_aliases if you want (still config-driven)
    rep_aliases = syn.get("rep_aliases")
    if isinstance(rep_aliases, dict) and rep_aliases:
        return {str(k).strip().lower(): str(v).strip().lower() for k, v in rep_aliases.items()}

    return {}
