import zmq
import json
import asyncio
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Pymol")

# Set up ZMQ context and socket
ctx = zmq.Context.instance()
socket = ctx.socket(zmq.REQ)
socket.connect("tcp://localhost:5555")  # Port must match UnityMol config

def send_unitymol_command(command: str):
    socket.send_string(command)
    response = json.loads(socket.recv().decode())
    if response.get("success", False):
        return response["result"]
    else:
        raise RuntimeError(f"Command failed: {response.get('stdout', '')}")

@mcp.tool()
def get_selection_list() -> str:
    """Get the current selection list from UnityMol."""
    return send_unitymol_command("getSelectionListString()")

@mcp.tool()
def load_pdb(filename: str) -> str:
    """Load a PDB file in UnityMol."""
    return send_unitymol_command(f"execScriptString('loadPDB(\"{filename}\")')")

