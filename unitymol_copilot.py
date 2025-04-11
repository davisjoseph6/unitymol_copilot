"""
UnityMol Copilot - FastAgent Integration

This module integrates the UnityMol ZMQ communication with FastAgent to create
a conversational interface for UnityMol.
"""

from mcp_agent.core.fastagent import FastAgent
import ollama
import json
import logging
import os
from unitymol_zmq import UnityMolZMQ

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("UnityMolCopilot")

class UnityMolCopilot:
    """
    A copilot for UnityMol that uses FastAgent and Ollama to provide a natural language
    interface to UnityMol's API.
    """
    
    def __init__(self, 
                 model_name="deepseek-coder-v2:16b", 
                 unitymol_host="localhost", 
                 unitymol_port=5555,
                 system_prompt=None):
        """
        Initialize the UnityMol Copilot.
        
        Args:
            model_name (str): The name of the Ollama model to use
            unitymol_host (str): The host where UnityMol is running
            unitymol_port (int): The port on which UnityMol's ZMQ server is listening
            system_prompt (str): Custom system prompt for the agent
        """
        self.model_name = model_name
        self.unitymol = UnityMolZMQ(host=unitymol_host, port=unitymol_port)
        
        # Default system prompt if none provided
        if system_prompt is None:
            self.system_prompt = """
            You are an expert assistant for UnityMol, a molecular visualization application.
            Your role is to help users interact with UnityMol by translating their natural language requests
            into appropriate UnityMol API calls.
            
            When responding to user requests:
            1. Understand what the user wants to accomplish with UnityMol
            2. Generate the appropriate UnityMol API call(s) to fulfill the request
            3. Execute the API call(s) and interpret the results
            4. Provide a clear, helpful response to the user
            
            Always format your UnityMol API calls exactly as they should be executed.
            If you're unsure about a request, ask for clarification.
            If a request requires multiple API calls, execute them in the appropriate sequence.
            """
        else:
            self.system_prompt = system_prompt
            
        # Initialize FastAgent
        self.agent = FastAgent(
            name="UnityMol Copilot",
            system_prompt=self.system_prompt,
            model=self.model_name,
            model_provider="ollama"
        )
        
        # Add tools to the agent
        self._register_tools()
        
        # Store conversation context
        self.context = {
            "loaded_structures": [],
            "current_selections": [],
            "last_commands": []
        }
        
        logger.info(f"UnityMol Copilot initialized with model {model_name}")
        
    def _register_tools(self):
        """
        Register tools with the FastAgent.
        """
        # Tool to execute UnityMol commands
        self.agent.register_tool(
            name="execute_unitymol_command",
            description="Execute a UnityMol API command and return the result",
            function=self._execute_unitymol_command,
            parameters=[
                {
                    "name": "command",
                    "type": "string",
                    "description": "The UnityMol API command to execute"
                }
            ]
        )
        
        # Tool to get available UnityMol commands
        self.agent.register_tool(
            name="get_unitymol_api_info",
            description="Get information about available UnityMol API commands",
            function=self._get_unitymol_api_info,
            parameters=[]
        )
        
        # Tool to update context
        self.agent.register_tool(
            name="update_context",
            description="Update the conversation context with new information",
            function=self._update_context,
            parameters=[
                {
                    "name": "context_updates",
                    "type": "object",
                    "description": "Updates to the conversation context"
                }
            ]
        )
        
    def _execute_unitymol_command(self, command):
        """
        Execute a UnityMol API command and return the result.
        
        Args:
            command (str): The UnityMol API command to execute
            
        Returns:
            dict: The result of the command execution
        """
        try:
            # Add command to history
            self.context["last_commands"].append(command)
            
            # Execute the command
            result = self.unitymol.send_command(command)
            
            # Update context based on command
            self._update_context_from_command(command, result)
            
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
    
    def _get_unitymol_api_info(self):
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
    
    def _update_context_from_command(self, command, result):
        """
        Update the conversation context based on the executed command and its result.
        
        Args:
            command (str): The executed command
            result (dict): The result of the command execution
        """
        # This is a simplified implementation - a real version would have more sophisticated parsing
        try:
            # Track loaded structures
            if "load(" in command or "fetch(" in command:
                if result.get("success", False):
                    # Extract structure name from result
                    structure_name = result.get("result", "").strip()
                    if structure_name and structure_name not in self.context["loaded_structures"]:
                        self.context["loaded_structures"].append(structure_name)
            
            # Track selections
            elif "select(" in command:
                if result.get("success", False):
                    # Extract selection name from command
                    import re
                    match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', command)
                    if match:
                        selection_name = match.group(1)
                        if selection_name not in self.context["current_selections"]:
                            self.context["current_selections"].append(selection_name)
            
            # Handle deletion of selections
            elif "deleteSelection(" in command:
                if result.get("success", False):
                    # Extract selection name from command
                    import re
                    match = re.search(r'deleteSelection\(["\']([^"\']+)["\']', command)
                    if match:
                        selection_name = match.group(1)
                        if selection_name in self.context["current_selections"]:
                            self.context["current_selections"].remove(selection_name)
        
        except Exception as e:
            logger.error(f"Error updating context from command: {e}")
    
    def _update_context(self, context_updates):
        """
        Update the conversation context with new information.
        
        Args:
            context_updates (dict): Updates to the conversation context
            
        Returns:
            dict: The updated context
        """
        try:
            for key, value in context_updates.items():
                if key in self.context:
                    self.context[key] = value
            
            return self.context
        except Exception as e:
            logger.error(f"Error updating context: {e}")
            return self.context
    
    def chat(self, message):
        """
        Process a user message and generate a response.
        
        Args:
            message (str): The user's message
            
        Returns:
            str: The copilot's response
        """
        try:
            # Check if UnityMol is connected
            if not self.unitymol.connected and not self.unitymol.test_connection():
                return "I'm unable to connect to UnityMol. Please make sure it's running with the ZMQ server enabled."
            
            # Process the message with FastAgent
            response = self.agent.chat(
                message=message,
                context=self.context
            )
            
            return response
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return f"I encountered an error while processing your request: {str(e)}"
    
    def run_as_tool(self, message):
        """
        Run the copilot as a tool for integration with other agents.
        
        Args:
            message (dict): The input message containing:
                - text (str): The user's message
                - context (dict, optional): Additional context
                
        Returns:
            dict: The result containing:
                - response (str): The copilot's response
                - commands (list): The executed UnityMol commands
                - results (list): The results of the executed commands
                - context (dict): The updated context
        """
        try:
            # Extract message and context
            text = message.get("text", "")
            if "context" in message:
                self.context.update(message["context"])
            
            # Process the message
            response = self.chat(text)
            
            # Return the result
            return {
                "response": response,
                "commands": self.context["last_commands"][-10:] if self.context["last_commands"] else [],
                "context": self.context
            }
        except Exception as e:
            logger.error(f"Error running as tool: {e}")
            return {
                "response": f"Error: {str(e)}",
                "commands": [],
                "context": self.context
            }

# Example usage
if __name__ == "__main__":
    # Create a UnityMol Copilot
    copilot = UnityMolCopilot()
    
    # Example conversation
    print("UnityMol Copilot initialized. Type 'exit' to quit.")
    print("Copilot: How can I help you with UnityMol today?")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit", "bye"]:
            break
        
        response = copilot.chat(user_input)
        print(f"Copilot: {response}")
    
    print("Copilot: Goodbye!")
