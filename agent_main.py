import asyncio
from mcp_agent.core.fastagent import FastAgent
from unitymol_tools import get_selection_list, load_pdb

agent = FastAgent(
    name="UnityMolCopilot",
    description="An intelligent assistant for molecular visualization in UnityMol.",
    tools=[get_selection_list, load_pdb],
    memory=True,
    verbose=True
)

def main():
    print("🧬 UnityMol Copilot is running. Type your command:")
    while True:
        prompt = input("You: ")
        result = agent.run(prompt)
        print("Copilot:", result)

if __name__ == "__main__":
    main()

