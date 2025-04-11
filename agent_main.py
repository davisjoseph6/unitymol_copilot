from fast_agent.agent import FastAgent

agent = FastAgent(
    name="UnityMolCopilot",
    description="A copilot for the UnityMol molecular viewer.",
    tools=[],  # We'll define tools later
    memory=True,
    verbose=True
)

while True:
    prompt = input("You: ")
    response = agent.run(prompt)
    print("Copilot:", response)

