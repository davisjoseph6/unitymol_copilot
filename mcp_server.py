"""
UnityMol Copilot - Updated implementation using FastMCP
"""

from mcp.server.fastmcp import FastMCP
import os, logging
from typing import Dict, Any, Optional, Union
from unitymol_zmq import UnityMolZMQ

# NEW:
from validator import parse_and_validate_molcommand
from executor import dsl_to_zmq_calls

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UnityMolCopilot")

# FastMCP server
mcp = FastMCP("unitymol-copilot")

# Global UnityMolZMQ instance
unitymol = None

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
            "command": command
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
                    "loadFromString(string fileName, string fileContent, ...)"
                ]
            },
            {
                "name": "Selections",
                "commands": [
                    "select(string selMDA, string name = \"selection\", bool createSelection = True, ...)",
                    "setCurrentSelection(string selName)",
                    "getSelectionListString()",
                    "deleteSelection(string selName)"
                ]
            },
            {
                "name": "Representations",
                "commands": [
                    "showSelection(string selName, string repType, ...)",
                    "hideSelection(string selName)",
                    "colorSelection(string selName, string type, Color col)",
                    "colorByChain(string selName, string type)"
                ]
            }
        ]
    }

@mcp.tool()
async def init_unitymol_copilot():
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

# NEW: Grammar-checked DSL tools
@mcp.tool()
async def validate_dsl(program: str) -> dict:
    """
    Validate molcommand DSL against the EBNF; return {ok, ast, errors}.
    """
    ok, ast, errors = parse_and_validate_molcommand(program)
    return {"ok": ok, "ast": ast, "errors": errors}

@mcp.tool()
async def execute_dsl(program: str) -> dict:
    """
    Validate DSL, transpile to UnityMol commands, execute sequentially, and aggregate results.
    """
    global unitymol
    ok, ast, errors = parse_and_validate_molcommand(program)
    if not ok:
        return {"success": False, "result": "", "stdout": "\n".join(errors), "commands": []}

    try:
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
            "raw": outputs
        }
    except Exception as e:
        logger.error(f"execute_dsl error: {e}")
        return {"success": False, "result": "", "stdout": str(e), "commands": []}

# Nice-to-have prompt helper
@mcp.tool()
async def scene_summary() -> dict:
    global unitymol
    unitymol = _ensure_unitymol()
    sel = unitymol.send_command("getSelectionListString()")
    return {
        "success": sel.get("success", False),
        "selections": sel.get("result", ""),
        "stdout": sel.get("stdout", "")
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
        import asyncio
        asyncio.run(mcp.serve())
    else:
        raise RuntimeError("FastMCP: no run()/serve() found")
    return 0

if __name__ == "__main__":
    raise SystemExit(main_sync())

