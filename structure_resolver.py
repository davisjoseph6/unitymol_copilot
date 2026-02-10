#!/usr/bin/env python3
"""Structure resolution for UnityMolX scenes.

We use the stable alias selection strategy:
- If selection "all_<pdbid>" already exists, do NOT load again.
- Otherwise load.

This avoids "1crn_2" duplicate loads and keeps targeting stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from config_loader import load_config
from selection_resolver import all_selection_name

_CFG = load_config()


@dataclass(frozen=True)
class ResolvedStructure:
    """Resolution result."""
    should_load: bool
    alias_selection: str  # e.g. all_1crn


def resolve_structure(scene_ctx: Dict[str, Any], pdbid: str) -> ResolvedStructure:
    """Return whether we should load pdbid, and the stable alias selection to target."""
    pdbid = (pdbid or "").strip().lower()
    alias = all_selection_name(pdbid)

    policy = _CFG.load_policy or {}
    idempotent = bool(policy.get("idempotent_load", True))
    allow_dupe = bool(policy.get("allow_duplicate_load", False))

    selections = scene_ctx.get("selections", []) or []
    names = {s.get("name") for s in selections if s.get("name")}

    exists = alias in names
    if idempotent and exists and not allow_dupe:
        return ResolvedStructure(should_load=False, alias_selection=alias)

    return ResolvedStructure(should_load=True, alias_selection=alias)
