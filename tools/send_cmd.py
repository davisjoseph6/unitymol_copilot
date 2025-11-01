import asyncio, os, sys
import mcp_server                      # your FastMCP tool module
import unitymol_zmq as um              # the bridge (already on PYTHONPATH)

async def main():
    # ensure a connected client exists for this process
    if getattr(mcp_server, "unitymol", None) is None:
        if um.unitymol is None:
            um.unitymol = um.UnityMolZMQ(
                host=os.environ.get("UMOL_HOST", "localhost"),
                port=int(os.environ.get("UMOL_PORT", "5555"))
            )
            if not um.unitymol.connect():
                print("Failed to connect to UnityMol ZMQ on %s:%s"
                      % (um.unitymol.host, um.unitymol.port))
                return
        # hand the same client to mcp_server
        mcp_server.unitymol = um.unitymol

    cmd = sys.argv[1] if len(sys.argv) > 1 else 'ls()'
    out = await mcp_server.execute_unitymol_command(cmd)
    print(out)

if __name__ == "__main__":
    asyncio.run(main())

