from fast_agent.tools import tool

@tool
def highlight_residue(residue_id: str):
    """Highlight a residue by ID in the UnityMol viewer."""
    # Communicate with Unity here (see below)
    return f"Residue {residue_id} highlighted."

