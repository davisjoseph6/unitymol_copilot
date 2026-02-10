#!/usr/bin/env python3
"""Selection resolution for UnityMolX scenes."""

from __future__ import annotations

from config_loader import load_config

_CFG = load_config()


def all_selection_name(structure_name: str) -> str:
    """Configured stable alias selection: all_<pdbid> by default."""
    tmpl = _CFG.selection_policy.get("all_selection_template", "all_{structure_name}")
    return tmpl.format(structure_name=(structure_name or "").strip().lower())
