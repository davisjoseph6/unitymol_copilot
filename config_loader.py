#!/usr/bin/env python3
"""Configuration loader for UnityMol Copilot.

Loads YAML/JSON configs from config/ and validates selected ones with schemas/.
Goal: move behavior rules into config so Python stays mostly orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent
CFG_DIR = ROOT / "config"
SCHEMA_DIR = ROOT / "schemas"


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _validate(instance: Dict[str, Any], schema_path: Path, *, label: str) -> None:
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join([f"- {label} {list(e.path)}: {e.message}" for e in errors])
        raise ValueError(f"Config validation failed:\n{msg}")


@dataclass(frozen=True)
class CopilotConfig:
    """All loaded configs."""
    dsl_registry: Dict[str, Any]
    synonyms: Dict[str, Any]
    rewrite_rules: Dict[str, Any]
    selection_policy: Dict[str, Any]
    load_policy: Dict[str, Any]
    context_requirements: Dict[str, Any]
    fallbacks: Dict[str, Any]


@lru_cache(maxsize=1)
def load_config() -> CopilotConfig:
    """Load and validate configs (cached)."""
    dsl_registry = _read_json(CFG_DIR / "dsl_registry.json")
    synonyms = _read_yaml(CFG_DIR / "synonyms.yaml")
    rewrite_rules = _read_yaml(CFG_DIR / "rewrite_rules.yaml")
    selection_policy = _read_yaml(CFG_DIR / "selection_policy.yaml")
    load_policy = _read_yaml(CFG_DIR / "load_policy.yaml")
    context_requirements = _read_yaml(CFG_DIR / "context_requirements.yaml")
    fallbacks = _read_yaml(CFG_DIR / "fallbacks.yaml")

    # Validate registry (you can add more schemas later)
    schema_path = SCHEMA_DIR / "dsl_registry.schema.json"
    if schema_path.exists():
        _validate(dsl_registry, schema_path, label="dsl_registry")

    return CopilotConfig(
        dsl_registry=dsl_registry,
        synonyms=synonyms,
        rewrite_rules=rewrite_rules,
        selection_policy=selection_policy,
        load_policy=load_policy,
        context_requirements=context_requirements,
        fallbacks=fallbacks,
    )
