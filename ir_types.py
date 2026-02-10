#!/usr/bin/env python3
"""Intermediate representation (IR) for actions before compiling to DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ActionIR:
    """Normalized action intent."""
    action: str              # "load", "show", "color", "hide"
    pdbid: Optional[str]     # "1crn" if relevant
    rep: Optional[str]       # "cartoon", "surface"...
    color: Optional[str]     # "red" if relevant
