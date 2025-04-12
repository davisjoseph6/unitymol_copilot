"""
UnityMol Copilot - Updated implementation using FastAgent

This module integrates the UnityMol ZMQ communication with FastAgent to create
a conversational interface for UnityMol.
"""

from mcp.server.fastmcp import FastMCP
import os

#import asyncio
import logging
import json
#from pathlib import Path
from typing import Dict, Any, Optional, Union

#from mcp_agent.core.fastagent import FastAgent
#from mcp_agent.core.prompt import Prompt
from unitymol_zmq import UnityMolZMQ

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilot")

# Initialize FastMCP server
mcp = FastMCP("unitymol-copilot")

# # Create the FastAgent application
# fast = FastAgent("UnityMol Copilot")

# Reference to the agent instance (will be set later)
#global agent

# Global UnityMolZMQ instance
unitymol = None

# Define tool schema for execute_unitymol_command
@mcp.tool()
async def execute_unitymol_command(command: str) -> dict:
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

# Define tool schema for get_unitymol_api_info
@mcp.tool()
async def get_unitymol_api_info() -> dict:
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

@mcp.tool()
async def init_unitymol_copilot():
    """
    Initialization entry point for the UnityMol Copilot.
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

    return {"success": True, "message": f"Initialized UnityMol Copilot with ZMQ connection"}
