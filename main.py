"""
UnityMol Copilot - Main Script

This script provides a command-line interface to the UnityMol Copilot.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path


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
        # Update the config file with the specified model if needed
        if args.model != "deepseek-coder-v2:16b":
            update_config_model(args.model)
        
        # Update the ZMQ connection settings
        from unitymol_zmq import UnityMolZMQ
        UnityMolZMQ.DEFAULT_HOST = args.host
        UnityMolZMQ.DEFAULT_PORT = args.port
        
        # Import and run the copilot
        from mcp_server import main_sync as copilot_main
        exit_code = copilot_main()
        return exit_code
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

def update_config_model(model_name):
    """
    Update the FastAgent config file with the specified model.
    
    Args:
        model_name (str): The name of the Ollama model to use
    """
    try:
        import yaml
        
        config_path = Path(__file__).parent / "fastagent.config.yaml"
        
        # Read the current config
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Update the model
        config['llm']['model'] = model_name
        
        # Write the updated config
        with open(config_path, 'w') as f:
            yaml.dump(config, f)
            
        logger.info(f"Updated config to use model: {model_name}")
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        raise

if __name__ == "__main__":
    exit(main())
