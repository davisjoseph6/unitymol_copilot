import asyncio
from mcp_agent.core.fastagent import FastAgent
from unitymol_tools import get_selection_list, load_pdb

# Create the application
fast = FastAgent("UnityMol Copilot")

# Define the agent
@fast.agent(
    name="unitymol_copilot",
    instruction="You are a helpful AI agent for molecular visualization in UnityMol.",
#    tools=[get_selection_list, load_pdb],
#    memory=True,
#    verbose=True
    )



async def main():
    print("🧬 UnityMol Copilot is running. Type your command:")
    # use the --model command line switch or agent arguments to change model
    async with fast.run() as agent:
        await agent()


if __name__ == "__main__":
    asyncio.run(main())

