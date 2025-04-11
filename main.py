from unitymol_agent import create_unitymol_agent

agent = create_unitymol_agent()

def main():
    print("🧬 UnityMol Copilot is ready.")
    while True:
        try:
            query = input("You: ")
            response = agent.run(query)
            print(f"Copilot: {response}")
        except KeyboardInterrupt:
            print("\nExiting Copilot.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()

