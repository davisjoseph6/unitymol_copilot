#!/usr/bin/env python3
"""Tests for idempotent load behavior (alias-selection based)."""

from structure_resolver import resolve_structure


def test_idempotent_load_skips_when_alias_exists():
    scene = {
        "selections": [
            {"name": "all_1crn"}
        ]
    }
    res = resolve_structure(scene, "1crn")
    assert res.should_load is False
    assert res.alias_selection == "all_1crn"
