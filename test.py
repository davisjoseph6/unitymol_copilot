"""
UnityMol Copilot - Test Script

This script tests the functionality of the updated UnityMol Copilot.
"""

import logging
import sys
import os
import asyncio
from pathlib import Path
from unitymol_zmq import UnityMolZMQ

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilotTest")

async def test_zmq_connection():
    """
    Test the ZMQ connection to UnityMol.
    
    Returns:
        bool: True if the connection is successful, False otherwise
    """
    logger.info("Testing ZMQ connection to UnityMol...")
    
    try:
        # Create a UnityMolZMQ instance
        unitymol = UnityMolZMQ()
        
        # Test the connection
        if unitymol.test_connection():
            logger.info("Successfully connected to UnityMol ZMQ server")
            unitymol.disconnect()
            return True
        else:
            logger.error("Failed to connect to UnityMol ZMQ server")
            return False
    except Exception as e:
        logger.error(f"Error testing ZMQ connection: {e}")
        return False

async def test_basic_commands():
    """
    Test basic UnityMol commands through the ZMQ connection.
    
    Returns:
        bool: True if all commands are successful, False otherwise
    """
    logger.info("Testing basic UnityMol commands...")
    
    try:
        # Create a UnityMolZMQ instance
        unitymol = UnityMolZMQ()
        
        # Connect to UnityMol
        if not unitymol.connect():
            logger.error("Failed to connect to UnityMol ZMQ server")
            return False
        
        # Test getSelectionListString command
        logger.info("Testing getSelectionListString command...")
        result = unitymol.send_command("getSelectionListString()")
        if not result.get('success', False):
            logger.error(f"getSelectionListString command failed: {result.get('stdout', 'Unknown error')}")
            unitymol.disconnect()
            return False
        logger.info(f"getSelectionListString result: {result['result']}")
        
        # Disconnect when done
        unitymol.disconnect()
        return True
    except Exception as e:
        logger.error(f"Error testing basic commands: {e}")
        return False

async def test_fastagent_import():
    """
    Test importing the FastAgent and related modules.
    
    Returns:
        bool: True if imports are successful, False otherwise
    """
    logger.info("Testing FastAgent imports...")
    
    try:
        # Try importing the necessary modules
        from mcp_agent.core.fastagent import FastAgent
        from mcp_agent.core.prompt import Prompt
        
        logger.info("Successfully imported FastAgent modules")
        return True
    except ImportError as e:
        logger.error(f"Error importing FastAgent modules: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during FastAgent import test: {e}")
        return False

async def test_config_file():
    """
    Test that the configuration file exists and is valid.
    
    Returns:
        bool: True if the config file is valid, False otherwise
    """
    logger.info("Testing configuration file...")
    
    try:
        config_path = Path(__file__).parent / "fastagent.config.yaml"
        
        # Check if the file exists
        if not config_path.exists():
            logger.error(f"Configuration file not found at {config_path}")
            return False
        
        # Try to load the file to verify it's valid YAML
        import yaml
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Check for required keys
        if 'llm' not in config:
            logger.error("Configuration file missing 'llm' section")
            return False
        
        if 'provider' not in config['llm'] or config['llm']['provider'] != 'ollama':
            logger.error("Configuration file missing or incorrect 'provider' in 'llm' section")
            return False
        
        if 'model' not in config['llm']:
            logger.error("Configuration file missing 'model' in 'llm' section")
            return False
        
        logger.info(f"Configuration file is valid, using model: {config['llm']['model']}")
        return True
    except Exception as e:
        logger.error(f"Error testing configuration file: {e}")
        return False

async def run_tests():
    """
    Run all tests for the UnityMol Copilot.
    
    Returns:
        bool: True if all tests pass, False otherwise
    """
    logger.info("Starting UnityMol Copilot tests...")
    
    # Track test results
    results = {
        "zmq_connection": False,
        "basic_commands": False,
        "fastagent_import": False,
        "config_file": False
    }
    
    # Test FastAgent imports
    results["fastagent_import"] = await test_fastagent_import()
    
    # Test configuration file
    results["config_file"] = await test_config_file()
    
    # Test ZMQ connection
    results["zmq_connection"] = await test_zmq_connection()
    
    # If ZMQ connection is successful, test basic commands
    if results["zmq_connection"]:
        results["basic_commands"] = await test_basic_commands()
    
    # Print test results
    logger.info("Test results:")
    for test, result in results.items():
        logger.info(f"  {test}: {'PASS' if result else 'FAIL'}")
    
    # Return True if all tests pass
    return all(results.values())

if __name__ == "__main__":
    # Check if UnityMol is running
    print("Make sure UnityMol is running with the ZMQ server enabled before running this test.")
    input("Press Enter to continue...")
    
    # Run the tests
    success = asyncio.run(run_tests())
    
    # Exit with appropriate status code
    sys.exit(0 if success else 1)
