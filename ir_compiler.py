#!/usr/bin/env python3
"""Compile IR into registry-valid DSL, using scene context + policies."""

from __future__ import annotations

from typing import Any, Dict, List

from config_loader import load_config
from ir_types import ActionIR
from structure_resolver import resolve_structure

_CFG = load_config()


def compile_ir(scene_ctx: Dict[str, Any], ir: ActionIR) -> str:
    """Compile a single IR action into DSL lines."""
    rep_aliases = _CFG.synonyms.get("rep_aliases", {}) or {}
    color_aliases = _CFG.synonyms.get("color_aliases", {}) or {}

    rep = rep_aliases.get(ir.rep, ir.rep) if ir.rep else None
    color = color_aliases.get(ir.color, ir.color) if ir.color else None

    lines: List[str] = []

    alias_sel = None
    if ir.pdbid:
        res = resolve_structure(scene_ctx, ir.pdbid)
        alias_sel = res.alias_selection
        if res.should_load and ir.action in {"load", "show", "color"}:
            lines.append(f'add_structure(PDBID="{ir.pdbid.lower()}")')

    if ir.action == "show" and alias_sel and rep:
        lines.append(f'show(sel="{alias_sel}", rep="{rep}")')

    if ir.action == "color" and alias_sel and rep and color:
        # Optionally reissue show before color if configured
        if _CFG.fallbacks.get("reissue_show_before_color", True):
            lines.append(f'show(sel="{alias_sel}", rep="{rep}")')
        lines.append(f'color(sel="{alias_sel}", rep="{rep}", color="{color}")')

    if ir.action == "hide" and alias_sel:
        lines.append(f'hide(sel="{alias_sel}")')

    return "\n".join(lines).strip()
