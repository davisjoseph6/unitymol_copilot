# file: tools/try_tools.py
import asyncio, json
from mcp_server import execute_unitymol_command, validate_dsl, execute_dsl, scene_summary

async def main():
    print(await execute_unitymol_command('ls()'))
    print(await execute_unitymol_command('fetch("1kx2")'))
    print(await scene_summary())

    ok = await validate_dsl('add_structure(PDBID="5iuf")')
    print(ok)

    out = await execute_dsl('add_structure(PDBID="5iuf")')
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    asyncio.run(main())

