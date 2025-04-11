"""
UnityMol Copilot - Main Script

This script provides a command-line interface to the UnityMol Copilot.
"""

import argparse
import logging
import os
from unitymol_copilot import UnityMolCopilot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilotCLI")

def main():
    """
    Main entry point for the UnityMol Copilot CLI.
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="UnityMol Copilot - Natural language interface for UnityMol")
    parser.add_argument("--host", default="localhost", help="Host where UnityMol is running")
    parser.add_argument("--port", type=int, default=5555, help="Port on which UnityMol's ZMQ server is listening")
    parser.add_argument("--model", default="deepseek-coder-v2:16b", help="Ollama model to use")
    parser.add_argument("--tool-mode", action="store_true", help="Run in tool mode (for integration with other agents)")
    args = parser.parse_args()
    
    try:
        # Create the UnityMol Copilot
        copilot = UnityMolCopilot(
            model_name=args.model,
            unitymol_host=args.host,
            unitymol_port=args.port
        )
        
        if args.tool_mode:
            # Tool mode for integration with other agents
            print("UnityMol Copilot running in tool mode. Send JSON messages to stdin.")
            print("Format: {\"text\": \"your message\", \"context\": {optional context}}")
            print("Type 'exit' to quit.")
            
            while True:
                try:
                    user_input = input()
                    if user_input.lower() == "exit":
                        break
                    
                    import json
                    message = json.loads(user_input)
                    result = copilot.run_as_tool(message)
                    print(json.dumps(result))
                except json.JSONDecodeError:
                    print(json.dumps({"error": "Invalid JSON input"}))
                except Exception as e:
                    print(json.dumps({"error": str(e)}))
        else:
            # Interactive conversational mode
            print("UnityMol Copilot initialized. Type 'exit' to quit.")
            print("Copilot: How can I help you with UnityMol today?")
            
            while True:
                user_input = input("You: ")
                if user_input.lower() in ["exit", "quit", "bye"]:
                    break
                
                response = copilot.chat(user_input)
                print(f"Copilot: {response}")
            
            print("Copilot: Goodbye!")
    
    except Exception as e:
        logger.error(f"Error in main: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
