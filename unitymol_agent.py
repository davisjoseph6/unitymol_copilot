from mcp_agent.core.fastagent import FastAgent
from unitymol_tools import get_selection, load_pdb, color_chain

def create_unitymol_agent() -> FastAgent:
    return FastAgent(
        name="UnityMolCopilot",
        description="An AI assistant for UnityMol molecular visualization.",
        tools=[get_selection, load_pdb, color_chain],
        memory=True,
        verbose=True,
    )

