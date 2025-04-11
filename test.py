"""
UnityMol Copilot - Test Script

This script tests the functionality of the UnityMol Copilot.
"""

import logging
import sys
import os
import time
from unitymol_zmq import UnityMolZMQ
from unitymol_copilot import UnityMolCopilot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilotTest")

def test_zmq_connection():
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

def test_basic_commands():
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

def test_copilot_initialization():
    """
    Test the initialization of the UnityMol Copilot.
    
    Returns:
        bool: True if initialization is successful, False otherwise
    """
    logger.info("Testing UnityMol Copilot initialization...")
    
    try:
        # Create a UnityMol Copilot instance
        copilot = UnityMolCopilot()
        
        # Check if the copilot is properly initialized
        if copilot.agent and copilot.unitymol:
            logger.info("UnityMol Copilot successfully initialized")
            return True
        else:
            logger.error("Failed to initialize UnityMol Copilot")
            return False
    except Exception as e:
        logger.error(f"Error initializing UnityMol Copilot: {e}")
        return False

def test_copilot_chat():
    """
    Test the chat functionality of the UnityMol Copilot.
    
    Returns:
        bool: True if chat is successful, False otherwise
    """
    logger.info("Testing UnityMol Copilot chat functionality...")
    
    try:
        # Create a UnityMol Copilot instance
        copilot = UnityMolCopilot()
        
        # Test a simple chat message
        logger.info("Sending test message to copilot...")
        response = copilot.chat("What commands are available in UnityMol?")
        
        if response:
            logger.info(f"Received response from copilot: {response[:100]}...")
            return True
        else:
            logger.error("Failed to receive response from copilot")
            return False
    except Exception as e:
        logger.error(f"Error testing copilot chat: {e}")
        return False

def run_tests():
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
        "copilot_initialization": False,
        "copilot_chat": False
    }
    
    # Test ZMQ connection
    results["zmq_connection"] = test_zmq_connection()
    
    # If ZMQ connection is successful, test basic commands
    if results["zmq_connection"]:
        results["basic_commands"] = test_basic_commands()
    
    # Test copilot initialization
    results["copilot_initialization"] = test_copilot_initialization()
    
    # If copilot initialization is successful and ZMQ connection works, test chat
    if results["copilot_initialization"] and results["zmq_connection"]:
        results["copilot_chat"] = test_copilot_chat()
    
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
    success = run_tests()
    
    # Exit with appropriate status code
    sys.exit(0 if success else 1)
