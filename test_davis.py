#!/usr/bin/env python3
import sys, asyncio, importlib.util, pathlib

# 1) Load the UnityMol ZMQ bridge from its real path
p = pathlib.Path.home() / "UnityMol-ScriptCollection/zmq/unitymol_zmq.py"
spec = importlib.util.spec_from_file_location("unitymol_zmq", p)
um = importlib.util.module_from_spec(spec); spec.loader.exec_module(um)

# 2) Register it in sys.modules under the exact name mcp_server is likely to import
sys.modules['unitymol_zmq'] = um

# (Optional safety): also register some common package-style aliases,
# in case mcp_server imports via a package path.
for alias in (
    'UnityMol_ScriptCollection.zmq.unitymol_zmq',
    'UnityMol.ScriptCollection.zmq.unitymol_zmq',  # just in case
):
    sys.modules[alias] = um

# 3) Connect once (no edits to the bridge file)
if um.unitymol is None:
    um.unitymol = um.UnityMolZMQ(host="localhost", port=5555)
    assert um.unitymol.connect(), "Could not connect to UnityMol ZMQ"

# 4) Import mcp_server AFTER the bridge exists & is registered
import mcp_server

# 5) Make sure mcp_server references the SAME module & has a direct handle to the client
print("same module object?", getattr(mcp_server, 'unitymol_zmq', None) is um)
if hasattr(mcp_server, 'unitymol_zmq'):
    mcp_server.unitymol_zmq = um

# Be generous with attribute names mcp_server might use internally
for name in ('unitymol', 'zmq_client', 'unitymol_client', 'client'):
    setattr(mcp_server, name, um.unitymol)

from mcp_server import execute_unitymol_command

async def run():
    print(await execute_unitymol_command('ls()'))
    print(await execute_unitymol_command('fetch("1kx2")'))

asyncio.run(run())
