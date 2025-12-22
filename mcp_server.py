#!/usr/bin/env python3
"""
UnityMol Copilot - Updated implementation using FastMCP

This server exposes tools to:
- Execute raw UnityMol commands over ZMQ
- Validate strict molcommand DSL (EBNF-based)
- Execute molcommand DSL by transpiling to UnityMol commands

DEV_MODE (MOLCOMMANDNL_DEV=1):
- Keeps strict grammar unchanged
- Normalizes a few known "LLM-ish" DSL formats *before* validation/parsing
- Returns dev debug info *when useful* (normalization changed or parse failed)

DEV_LOOSE (MOLCOMMANDNL_DEV_LOOSE=1):
- Only active when DEV_MODE is enabled
- Splits semicolon-separated statements into lines (best-effort)
- Drops non-DSL lines, strips list markers, strips trailing '.' / ';' (best-effort)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from unitymol_zmq import UnityMolZMQ
from validator import parse_and_validate_molcommand
from executor import dsl_to_zmq_calls
from dsl_normalizer import normalize_dsl, dev_mode_enabled

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("UnityMolCopilot")

# FastMCP server
mcp = FastMCP("unitymol-copilot")

# Global UnityMolZMQ instance
unitymol: UnityMolZMQ | None = None


def _ensure_unitymol() -> UnityMolZMQ:
    """
    Lazily create and cache a single UnityMolZMQ client, using env UMOL_HOST/UMOL_PORT.
    """
    global unitymol
    if unitymol is None:
        host = os.environ.get("UMOL_HOST", "localhost")
        port = int(os.environ.get("UMOL_PORT", "5555"))
        client = UnityMolZMQ(host=host, port=port)
        if not client.connect():
            raise ConnectionError(f"Could not connect to UnityMol ZMQ at {host}:{port}")
        unitymol = client
    return unitymol


def _maybe_normalize(program: str) -> tuple[bool, str, dict]:
    """
    If DEV_MODE is enabled, normalize the DSL-ish text before parsing/validation.
    Returns (dev_enabled, normalized_program, normalize_info).
    """
    dev = dev_mode_enabled()
    norm, ninfo = normalize_dsl(program, dev=dev)
    return dev, norm, ninfo


def _execute_ast(ast: list[dict[str, Any]]) -> dict:
    """
    Execute an already-validated AST via UnityMol ZMQ.
    Returns the aggregated execution response used by execute_dsl.
    """
    global unitymol

    unitymol = _ensure_unitymol()
    commands = dsl_to_zmq_calls(ast)

    outputs = []
    for cmd in commands:
        out = unitymol.send_command(cmd)
        outputs.append({"command": cmd, **out})

    success = all(o.get("success", False) for o in outputs)
    last = outputs[-1] if outputs else {}

    return {
        "success": success,
        "result": last.get("result", ""),
        "stdout": "\n".join(o.get("stdout", "") for o in outputs if o.get("stdout")),
        "commands": [o["command"] for o in outputs],
        "raw": outputs,
    }


def _attach_dev(resp: Dict[str, Any], *, dev: bool, ok: bool, ninfo: dict, norm: str) -> None:
    """
    Attach DEV debug info only when it adds value:
    - normalization changed something OR
    - parse/validate failed OR
    - execution failed (we pass ok=False in that path)
    """
    if not dev:
        return
    if ninfo.get("changed") or not ok:
        resp["dev"] = {"normalized_dsl": norm, "normalize_info": ninfo}


@mcp.tool()
async def execute_unitymol_command(command: str) -> dict:
    """
    Execute a UnityMol API command and return the result.
    """
    global unitymol
    try:
        unitymol = _ensure_unitymol()
        result = unitymol.send_command(command)
        return {
            "success": result.get("success", False),
            "result": result.get("result", ""),
            "stdout": result.get("stdout", ""),
            "command": command,
        }
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return {"success": False, "result": "", "stdout": str(e), "command": command}


@mcp.tool()
async def get_unitymol_api_info() -> dict:
    """Lightweight listing of common API calls."""
    return {
        "categories": [
            {
                "name": "Structure Loading",
                "commands": [
                    "fetch(string PDBId, bool usemmCIF = True, bool readHetm = True, bool forceDSSP = False, bool showDefaultRep = True, bool center = True, bool modelsAsTraj = True, int forceStructureType = -1, bool bioAssembly = False)",
                    "load(string filePath, bool readHetm = True, bool forceDSSP = False, bool showDefaultRep = True, bool center = True, bool modelsAsTraj = True, int forceStructureType = -1)",
                    "loadFromString(string fileName, string fileContent, ...)",
                ],
            },
            {
                "name": "Selections",
                "commands": [
                    'select(string selMDA, string name = "selection", bool createSelection = True, ...)',
                    "setCurrentSelection(string selName)",
                    "getSelectionListString()",
                    "deleteSelection(string selName)",
                ],
            },
            {
                "name": "Representations",
                "commands": [
                    "showSelection(string selName, string repType, ...)",
                    "hideSelection(string selName)",
                    "colorSelection(string selName, string type, Color col)",
                    "colorByChain(string selName, string type)",
                ],
            },
        ]
    }


@mcp.tool()
async def init_unitymol_copilot() -> dict:
    """
    Explicit initializer (optional). Uses UMOL_HOST/UMOL_PORT if set.
    """
    global unitymol
    try:
        unitymol = _ensure_unitymol()
    except Exception as e:
        logger.error(f"Failed to connect to UnityMol: {e}")
        return {"success": False, "message": str(e)}
    logger.info("Successfully connected to UnityMol")
    return {"success": True, "message": "Initialized UnityMol Copilot with ZMQ connection"}


@mcp.tool()
async def validate_dsl(program: str) -> dict:
    """
    Validate molcommand DSL against the EBNF; return {ok, ast, errors}.
    In DEV mode, normalize first and include debug info when useful.
    """
    dev, norm, ninfo = _maybe_normalize(program)

    ok, ast, errors = parse_and_validate_molcommand(norm)
    resp: Dict[str, Any] = {"ok": ok, "ast": ast, "errors": errors}

    _attach_dev(resp, dev=dev, ok=ok, ninfo=ninfo, norm=norm)
    return resp


@mcp.tool()
async def execute_dsl(program: str) -> dict:
    """
    Validate DSL, transpile to UnityMol commands, execute sequentially, and aggregate results.
    In DEV mode, normalize first and include debug info when useful.
    """
    dev, norm, ninfo = _maybe_normalize(program)

    ok, ast, errors = parse_and_validate_molcommand(norm)
    if not ok:
        resp: Dict[str, Any] = {
            "success": False,
            "result": "",
            "stdout": "\n".join(errors),
            "commands": [],
        }
        _attach_dev(resp, dev=dev, ok=ok, ninfo=ninfo, norm=norm)
        return resp

    try:
        out = _execute_ast(ast)
        _attach_dev(out, dev=dev, ok=True, ninfo=ninfo, norm=norm)
        return out
    except Exception as e:
        logger.error(f"execute_dsl error: {e}")
        resp = {"success": False, "result": "", "stdout": str(e), "commands": []}
        # execution failed => attach dev info even if normalization didn't change
        _attach_dev(resp, dev=dev, ok=False, ninfo=ninfo, norm=norm)
        return resp


@mcp.tool()
async def scene_summary() -> dict:
    """
    Nice-to-have prompt helper: return current selection list string.
    """
    global unitymol
    unitymol = _ensure_unitymol()
    sel = unitymol.send_command("getSelectionListString()")
    return {
        "success": sel.get("success", False),
        "selections": sel.get("result", ""),
        "stdout": sel.get("stdout", ""),
    }


def main_sync() -> int:
    global unitymol
    try:
        unitymol = _ensure_unitymol()
    except Exception as e:
        logger.error(f"Failed to connect to UnityMol. Is the ZMQ server running on 5555? {e}")
        return 1

    logger.info("UnityMolZMQ ready; FastMCP tools registered.")

    if hasattr(mcp, "run"):
        mcp.run()
    elif hasattr(mcp, "serve"):
        asyncio.run(mcp.serve())
    else:
        raise RuntimeError("FastMCP: no run()/serve() found")

    return 0


if __name__ == "__main__":
    raise SystemExit(main_sync())

