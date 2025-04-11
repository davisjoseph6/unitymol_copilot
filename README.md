"""
UnityMol Copilot - README

A natural language interface for UnityMol using FastAgent and Ollama.
"""

# UnityMol Copilot

UnityMol Copilot is a natural language interface for UnityMol, allowing users to control the molecular visualization application through conversational commands. It uses the DeepSeek-Coder-V2 language model via Ollama to interpret user requests and generate appropriate UnityMol API calls.

## Features

- Natural language interface to UnityMol's API
- Support for all UnityMol API functions
- Conversational mode for direct interaction
- Tool mode for integration with more complex agentic setups
- Context-aware interactions that remember loaded structures and selections
- Robust error handling and logging

## Requirements

- Python 3.6+
- Ollama with DeepSeek-Coder-V2 model installed
- UnityMol with ZMQ server enabled
- FastAgent from mcp_agent.core.fastagent
- PyZMQ library

## Installation

1. Make sure you have Ollama installed and the DeepSeek-Coder-V2 model pulled:
   ```
   ollama pull deepseek-coder-v2:16b
   ```

2. Install the required Python packages:
   ```
   pip install pyzmq mcp_agent
   ```

3. Clone or download this repository to your local machine.

## Usage

### Starting UnityMol with ZMQ Server

Make sure UnityMol is running with its ZMQ server enabled. The default port is 5555.

### Running in Conversational Mode

To start the UnityMol Copilot in conversational mode:

```
python main.py --host localhost --port 5555 --model deepseek-coder-v2:16b
```

You can then interact with the copilot by typing natural language requests:

```
You: Load PDB file 1CRN
Copilot: I'll load the PDB file 1CRN for you. Let me do that now.

I've executed the command: fetch("1CRN")

The structure has been successfully loaded. The result is "1CRN", which means the structure with ID 1CRN has been loaded into UnityMol. You can now visualize and manipulate this protein structure.

Would you like me to apply any specific visualization or representation to this structure?
```

### Running in Tool Mode

To start the UnityMol Copilot in tool mode for integration with other agents:

```
python main.py --tool-mode --host localhost --port 5555 --model deepseek-coder-v2:16b
```

In tool mode, you can send JSON messages to the copilot's stdin:

```json
{"text": "Load PDB file 1CRN"}
```

The copilot will respond with a JSON object containing the response, executed commands, and updated context:

```json
{
  "response": "I've loaded the PDB file 1CRN for you...",
  "commands": ["fetch(\"1CRN\")"],
  "context": {
    "loaded_structures": ["1CRN"],
    "current_selections": [],
    "last_commands": ["fetch(\"1CRN\")"]
  }
}
```

## Testing

To test the UnityMol Copilot functionality:

```
python test.py
```

This will run a series of tests to verify the ZMQ connection, basic commands, copilot initialization, and chat functionality.

## Architecture

The UnityMol Copilot consists of the following components:

1. **UnityMolZMQ**: Handles communication with UnityMol through its ZMQ server
2. **UnityMolCopilot**: Integrates FastAgent with the ZMQ communication layer
3. **Main Script**: Provides a command-line interface to the UnityMol Copilot

For more details, see the `architecture.md` file.

## Example Commands

Here are some example commands you can try with the UnityMol Copilot:

- "Load PDB file 1CRN"
- "Show the protein as cartoon"
- "Color the protein by chain"
- "Select all water molecules"
- "Hide hydrogens"
- "Take a screenshot"
- "What structures are currently loaded?"
- "What selections are available?"

## Limitations

- The copilot requires UnityMol to be running with the ZMQ server enabled
- Complex requests may require multiple interactions
- The copilot's understanding is limited by the language model's capabilities

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- UnityMol team for creating the molecular visualization application
- DeepSeek AI for the DeepSeek-Coder-V2 model
- Ollama for providing easy access to local language models
- FastAgent for the agentic framework
