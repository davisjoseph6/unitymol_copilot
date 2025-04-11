"""
UnityMol Copilot - Updated implementation using FastAgent

This module integrates the UnityMol ZMQ communication with FastAgent to create
a conversational interface for UnityMol.
"""

import asyncio
import logging
import json
from pathlib import Path
from mcp_agent.core.fastagent import FastAgent
from mcp_agent.core.prompt import Prompt
from unitymol_zmq import UnityMolZMQ

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilot")

# Create the FastAgent application
fast = FastAgent("UnityMol Copilot")

# Global UnityMolZMQ instance
unitymol = None

@fast.agent(
    "unitymol_copilot",
    instruction="""
    You are an expert assistant for UnityMol, a molecular visualization application.
    Your role is to help users interact with UnityMol by translating their natural language requests
    into appropriate UnityMol API calls.
    
    When responding to user requests:
    1. Understand what the user wants to accomplish with UnityMol
    2. Generate the appropriate UnityMol API call(s) to fulfill the request
    3. Execute the API call(s) using the execute_unitymol_command tool and interpret the results
    4. Provide a clear, helpful response to the user
    
    Always format your UnityMol API calls exactly as they should be executed.
    If you're unsure about a request, ask for clarification.
    If a request requires multiple API calls, execute them in the appropriate sequence.
    
    Keep track of loaded structures and selections to provide context-aware assistance.
    """
)
async def main():
    """
    Main entry point for the UnityMol Copilot.
    """
    global unitymol
    
    # Initialize UnityMolZMQ
    unitymol = UnityMolZMQ()
    
    # Test connection to UnityMol
    if not unitymol.test_connection():
        logger.error("Failed to connect to UnityMol. Make sure it's running with the ZMQ server enabled.")
        print("Failed to connect to UnityMol. Make sure it's running with the ZMQ server enabled.")
        return
    
    logger.info("Successfully connected to UnityMol")
    print("Successfully connected to UnityMol")
    
    # Start interactive session
    async with fast.run() as agent:
        await agent.interactive()

# Tool to execute UnityMol commands
@fast.tool(
    name="execute_unitymol_command",
    description="Execute a UnityMol API command and return the result",
    parameters=[
        {
            "name": "command",
            "type": "string",
            "description": "The UnityMol API command to execute"
        }
    ]
)
def execute_unitymol_command(command):
    """
    Execute a UnityMol API command and return the result.
    
    Args:
        command (str): The UnityMol API command to execute
        
    Returns:
        dict: The result of the command execution
    """
    global unitymol
    
    try:
        # Execute the command
        result = unitymol.send_command(command)
        
        return {
            "success": result.get("success", False),
            "result": result.get("result", ""),
            "stdout": result.get("stdout", ""),
            "command": command
        }
    except Exception as e:
        logger.error(f"Error executing command '{command}': {e}")
        return {
            "success": False,
            "result": "",
            "stdout": str(e),
            "command": command
        }

# Tool to get available UnityMol commands
@fast.tool(
    name="get_unitymol_api_info",
    description="Get information about available UnityMol API commands",
    parameters=[]
)
def get_unitymol_api_info():
    """
    Get information about available UnityMol API commands.
    
    Returns:
        dict: Information about UnityMol API commands
    """
    # This is a simplified version - in a real implementation, this would
    # provide more comprehensive API documentation
    return {
        "categories": [
            {
                "name": "Structure Loading",
                "commands": [
                    "fetch(string PDBId, bool usemmCIF = True, bool readHetm = True, bool forceDSSP = False, bool showDefaultRep = True, bool center = True, bool modelsAsTraj = True, int forceStructureType = -1, bool bioAssembly = False)",
                    "load(string filePath, bool readHetm = True, bool forceDSSP = False, bool showDefaultRep = True, bool center = True, bool modelsAsTraj = True, int forceStructureType = -1)",
                    "loadFromString(string fileName, string fileContent, bool readHetm = True, bool forceDSSP = False, bool showDefaultRep = True, bool center = True, bool modelsAsTraj = True, int forceStructureType = -1)"
                ]
            },
            {
                "name": "Selections",
                "commands": [
                    "select(string selMDA, string name = \"selection\", bool createSelection = True, bool addToExisting = False, bool forceCreate = False)",
                    "setCurrentSelection(string selName)",
                    "getSelectionListString()",
                    "deleteSelection(string selName)"
                ]
            },
            {
                "name": "Representations",
                "commands": [
                    "showSelection(string selName, string repType, bool showBonds = True, bool showSideChains = True, bool showBackbone = True, bool showHydrogens = False)",
                    "hideSelection(string selName)",
                    "colorSelection(string selName, string type, Color col)",
                    "colorByChain(string selName, string type)"
                ]
            }
        ]
    }

# Run the application
if __name__ == "__main__":
    asyncio.run(main())
