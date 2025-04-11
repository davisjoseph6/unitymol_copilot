import zmq
import json

class UnityMolZMQClient:
    def __init__(self, address="tcp://localhost:5555"):
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(address)

    def send_command(self, command: str) -> str:
        self.socket.send_string(command)
        response = json.loads(self.socket.recv().decode())

        if response.get("success"):
            return response["result"]
        else:
            raise RuntimeError(f"UnityMol command failed:\n{response.get('stdout', '')}")

