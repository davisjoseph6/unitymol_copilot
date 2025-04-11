from fast_agent.tools import tool
from zmq_client import UnityMolZMQClient

client = UnityMolZMQClient()

@tool
def get_selection() -> str:
    """Get the current molecular selection in UnityMol."""
    return client.send_command("getSelectionListString()")

@tool
def load_pdb(file_path: str) -> str:
    """Load a PDB file in UnityMol."""
    return client.send_command(f'execScriptString("loadPDB(\\"{file_path}\\")")')

@tool
def color_chain(chain: str, color: str) -> str:
    """Color a chain with a given color."""
    return client.send_command(f'execScriptString("colorChain(\\"{chain}\\", \\"{color}\\")")')

