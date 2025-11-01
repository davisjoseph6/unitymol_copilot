#!/usr/bin/env python3
"""
UnityMol Copilot – end-to-end pipeline tests

Covers:
  A) Raw ZMQ (ls, fetch, scene_summary)
  B) DSL: add_structure(PDBID=…)
  C) DSL: show an existing UnityMol selection (no select())
  D) DSL: color_by_chain on that selection
  E) DSL: hide then re-show
  F) DSL: (optional) add_structure(filePath=…) via UMOL_TEST_FILEPATH
  G) Negative cases: invalid PDB / both args
"""

import os, sys, json, asyncio

# Make project root importable when running from tests/
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mcp_server import (
    execute_unitymol_command,
    validate_dsl,
    execute_dsl,
    scene_summary,
)

# ----- small helpers ---------------------------------------------------------
def hdr(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def pretty(obj):
    print(json.dumps(obj, indent=2))

async def must_success(label: str, coro):
    hdr(label)
    out = await coro
    pretty(out)
    ok = out.get("success", False)
    if not ok:
        raise SystemExit(f"[FAIL] {label}: success=False")
    return out

async def must_validate_ok(label: str, dsl: str, expect_ok: bool = True):
    hdr(f"{label}  DSL:\n{dsl}")
    v = await validate_dsl(dsl)
    pretty(v)
    if bool(v.get("ok")) != expect_ok:
        state = "ok" if expect_ok else "not ok"
        raise SystemExit(f"[FAIL] {label}: expected validator {state}")
    return v

# ----- main battery ----------------------------------------------------------
async def main():
    # A) Raw ZMQ: list assets, fetch 1kx2, show selections
    await must_success("A1) ZMQ ls()", execute_unitymol_command('ls()'))
    await must_success("A2) ZMQ fetch(1kx2)", execute_unitymol_command('fetch("1kx2")'))
    sel_info = await must_success("A3) scene_summary()", scene_summary())
    selections_str = sel_info.get("selections", "")

    # Choose a selection that likely exists for 1kx2
    candidate_names = [
        "all_1kx2_3", "all_1kx2_2", "all_1kx2",
        "1kx2_protein_or_nucleic", "1kx2_3_protein_or_nucleic"
    ]
    target_sel = None
    for name in candidate_names:
        if name in selections_str:
            target_sel = name
            break
    if not target_sel:
        print("[WARN] No familiar 1kx2 selection found; falling back to 'all_1kx2'")
        target_sel = "all_1kx2"

    # B) DSL: add_structure(PDBID="5iuf")
    dsl_b = 'add_structure(PDBID="5iuf")'
    await must_validate_ok("B) validate add_structure(PDBID)", dsl_b, expect_ok=True)
    await must_success("B) execute add_structure(PDBID)", execute_dsl(dsl_b))

    # C) DSL: show an existing selection directly (no select())
    dsl_c = f'show(sel="{target_sel}", rep="cartoon")'
    await must_validate_ok("C) validate show(existing selection)", dsl_c, expect_ok=True)
    await must_success("C) execute show(existing selection)", execute_dsl(dsl_c))

    # D) DSL: color_by_chain on the same selection
    dsl_d = f'color_by_chain(sel="{target_sel}", target="cartoon")'
    await must_validate_ok("D) validate color_by_chain", dsl_d, expect_ok=True)
    await must_success("D) execute color_by_chain", execute_dsl(dsl_d))

    # E) DSL: hide then re-show the same selection
    dsl_e = f'hide(sel="{target_sel}"); show(sel="{target_sel}", rep="cartoon")'
    await must_validate_ok("E) validate hide+show", dsl_e, expect_ok=True)
    await must_success("E) execute hide+show", execute_dsl(dsl_e))

    # E-alt) newline-separated version (exercise NEWLINE separator)
    dsl_e2 = f'show(sel="{target_sel}", rep="cartoon")\ncolor_by_chain(sel="{target_sel}", target="cartoon")'
    await must_validate_ok("E-alt) validate newline separation", dsl_e2, expect_ok=True)
    await must_success("E-alt) execute newline separation", execute_dsl(dsl_e2))

    # F) Optional filePath test (set UMOL_TEST_FILEPATH if you want this)
    test_path = os.environ.get("UMOL_TEST_FILEPATH", "").strip()
    if test_path:
        dsl_f = f'add_structure(filePath="{test_path}")'
        try:
            await must_validate_ok("F) validate add_structure(filePath)", dsl_f, expect_ok=True)
            await must_success("F) execute add_structure(filePath)", execute_dsl(dsl_f))
        except SystemExit as e:
            print("[WARN] Optional filePath test failed:", e)
            print("       (This step is optional and does not fail the whole suite.)")

    # G) Negative tests
    dsl_g1 = 'add_structure(PDBID="zzz0")'  # invalid PDB id (must start with a digit)
    await must_validate_ok("G1) validate invalid PDB", dsl_g1, expect_ok=False)

    dsl_g2 = 'add_structure(PDBID="1abc", filePath="foo.pdb")'  # both args -> invalid by grammar/semantics
    await must_validate_ok("G2) validate both args", dsl_g2, expect_ok=False)

    print("\n🎉 All requested tests completed.\n"
          "Visually verify in Unity: cartoon shows for the chosen selection, colors by chain apply, hide & re-show work.\n")

if __name__ == "__main__":
    asyncio.run(main())

