#!/usr/bin/env python3
"""Quick manual tool runner for UnityMol Copilot (async)."""

import asyncio
import json

from mcp_server import (
    execute_unitymol_command,
    validate_dsl,
    execute_dsl,
    scene_summary,
    scene_context,
)


async def main():
    # 0) Context before doing anything
    print("\n=== SCENE CONTEXT (before) ===")
    print(json.dumps(await scene_context(compact=False), indent=2))

    # 1) Raw UnityMol checks
    print("\n=== ZMQ ls() ===")
    print(await execute_unitymol_command("ls()"))

    print("\n=== ZMQ fetch(1kx2) ===")
    print(await execute_unitymol_command('fetch("1kx2")'))

    # 2) Existing scene summary
    print("\n=== SCENE SUMMARY ===")
    print(await scene_summary())

    # 3) Context after fetch
    print("\n=== SCENE CONTEXT (after fetch) ===")
    print(json.dumps(await scene_context(compact=False), indent=2))

    # 4) DSL validation + exec
    print("\n=== VALIDATE DSL add_structure(5iuf) ===")
    ok = await validate_dsl('add_structure(PDBID="5iuf")')
    print(ok)

    print("\n=== EXEC DSL add_structure(5iuf) ===")
    out = await execute_dsl('add_structure(PDBID="5iuf")')
    print(json.dumps(out, indent=2))

    # 5) Context after DSL exec
    print("\n=== SCENE CONTEXT (after DSL) ===")
    print(json.dumps(await scene_context(compact=False), indent=2))


if __name__ == "__main__":
    asyncio.run(main())

