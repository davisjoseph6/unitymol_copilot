#!/usr/bin/env python3
import asyncio, json, os
from mcp_server import validate_dsl, execute_dsl

DSL = """
add_structure(PDBID="1crn")
select(query="all", name="all_1crn")
show(sel="all_1crn", rep="cartoon")
color(sel="all_1crn", rep="cartoon", color="red")
""".strip()

async def main():
    print("DSL:\n", DSL)
    v = await validate_dsl(DSL)
    print("\nvalidate_dsl:\n", json.dumps(v, indent=2))
    if not v.get("ok"):
        raise SystemExit(1)
    r = await execute_dsl(DSL)
    print("\nexecute_dsl:\n", json.dumps(r, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
