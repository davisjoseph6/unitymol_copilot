#!/usr/bin/env python3
import asyncio, json, os, re, subprocess, sys
# Ensure FastMCP tools are importable
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mcp_server import validate_dsl, execute_dsl

def extract_cleaned_dsl(text: str) -> str:
    """
    Find the line immediately following '=== Cleaned DSL ==='
    and return it stripped.
    """
    m = re.search(r"^=== Cleaned DSL ===\s*\n(.+?)\s*\n", text, flags=re.M|re.S)
    if not m:
        raise RuntimeError("Could not find Cleaned DSL block in molcommandnl output.")
    return m.group(1).strip()

async def run_nl_to_unitymol():
    # Run molcommandnl example to generate DSL
    # Adjust the path if your script location differs
    mcnl_root = os.path.expanduser("~/molcommandnl")
    script = os.path.join(mcnl_root, "script", "example-usage.py")
    if not os.path.exists(script):
        raise FileNotFoundError(f"molcommandnl example script not found at: {script}")

    print("[molcommandnl] running example-usage.py ...")
    out = subprocess.check_output([sys.executable, script], text=True)
    print("[molcommandnl] OK; parsing cleaned DSL...")
    dsl = extract_cleaned_dsl(out)
    print("CLEANED DSL:\n", dsl)

    print("\n[validator] validate_dsl(...)")
    v = await validate_dsl(dsl)
    print(v)

    if not v.get("ok"):
        print("\nValidation failed; aborting.")
        sys.exit(1)

    print("\n[executor] execute_dsl(...)")
    res = await execute_dsl(dsl)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(run_nl_to_unitymol())

