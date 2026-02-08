#!/usr/bin/env python3
"""Probe UnityMolX representation + coloring commands via ZMQ safely.

What this script does:
- Try to load a structure robustly:
    1) fetch(pdb, usemmCIF=True) + poll
    2) fetch(pdb, usemmCIF=False) + poll
    3) RCSB download + loadFromString(...) + poll
- Ensure a named selection exists: select("all", "all_<requested>")
- Probe showSelection() with candidate repType strings
- Probe colorSelection() using:
    1) string color overload: "red" (most robust)
    2) UnityEngine.Color(...) expressions as fallback
- Optionally probe colorBy* schemes
- Uses fresh REQ socket + timeouts so it never hangs.

Important:
- UnityMol often returns {"success": true} even when it prints warnings/errors to stdout.
  We treat stdout containing "[Warning]" or "[Error]" as failure for probing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Dict, List

import zmq


ZMQ_TIMEOUT_MS_DEFAULT = 3000
ZMQ_TIMEOUT_MS_FETCH = 12000
ZMQ_TIMEOUT_MS_LOADSTR = 20000

POLL_INTERVAL_S = 0.4
POLL_TIMEOUT_S = 20.0


def _roundtrip(command: str, host: str, port: int, timeout_ms: int) -> Dict[str, Any]:
    """Send one command over a fresh ZMQ REQ socket with timeouts; return parsed JSON or error."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.connect(f"tcp://{host}:{port}")

    try:
        sock.send_string(command)
        raw = sock.recv().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"success": False, "result": "", "stdout": raw}
    except Exception as e:
        return {"success": False, "result": "", "stdout": f"[timeout/error] {e}"}
    finally:
        sock.close()


def _stdout_has_problem(stdout: str) -> bool:
    s = (stdout or "").replace("\r", "")
    return ("[Warning]" in s) or ("[Error]" in s)


def _ok(out: Dict[str, Any]) -> bool:
    """Consider both JSON 'success' and stdout warnings/errors."""
    if not bool(out.get("success", False)):
        return False
    if _stdout_has_problem(out.get("stdout", "") or ""):
        return False
    return True


def _fmt(out: Dict[str, Any], max_stdout: int = 160) -> str:
    stdout = (out.get("stdout", "") or "").replace("\r", "")
    if len(stdout) > max_stdout:
        stdout = stdout[:max_stdout] + "…"
    return f"success={out.get('success', False)!r} result={out.get('result', '')!r} stdout={stdout!r}"


def _parse_listish(value: Any) -> List[str]:
    """Parse UnityMol list-ish results robustly (supports JSON list strings and [a, b] strings)."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    s = str(value).strip()
    if not s or s == "[]":
        return []

    # JSON list string
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass

    # bracketed list: [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
        return [p for p in parts if p]

    # fallback: newline-separated
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def _poll_until_loaded(host: str, port: int) -> Dict[str, Any]:
    """Poll for evidence a structure is really loaded; returns best-effort info dict."""
    start = time.monotonic()
    last_struct_payload: Dict[str, Any] = {}
    last_sel_payload: Dict[str, Any] = {}

    while (time.monotonic() - start) < POLL_TIMEOUT_S:
        struct_payload = _roundtrip("getStructureListString()", host, port, ZMQ_TIMEOUT_MS_DEFAULT)
        last_struct_payload = struct_payload
        if _ok(struct_payload):
            structs = _parse_listish(struct_payload.get("result"))
            if structs:
                return {"ok": True, "structures": structs, "selections": [], "source": "getStructureListString"}

        sel_payload = _roundtrip("getSelectionListString()", host, port, ZMQ_TIMEOUT_MS_DEFAULT)
        last_sel_payload = sel_payload
        if _ok(sel_payload):
            sels = _parse_listish(sel_payload.get("result"))
            if sels:
                return {"ok": True, "structures": [], "selections": sels, "source": "getSelectionListString"}

        time.sleep(POLL_INTERVAL_S)

    return {
        "ok": False,
        "structures": [],
        "selections": [],
        "last_structure_payload": last_struct_payload,
        "last_selection_payload": last_sel_payload,
        "source": "timeout",
    }


def _rcsb_url(pdb_id: str, fmt: str) -> str:
    pdb = pdb_id.strip().upper()
    f = (fmt or "pdb").strip().lower()
    ext = "pdb" if f == "pdb" else "cif"
    return f"https://files.rcsb.org/download/{pdb}.{ext}"


def _download_rcsb(pdb_id: str, fmt: str = "pdb") -> str:
    """Download a structure file from RCSB and return its text."""
    url = _rcsb_url(pdb_id, fmt)
    return urllib.request.urlopen(url, timeout=15).read().decode("utf-8", errors="replace")


def _try_robust_load(host: str, port: int, pdb: str) -> bool:
    """Try fetch mmCIF -> fetch PDB -> RCSB loadFromString, returning True if evidence appears."""
    print("=== FETCH (mmCIF=True) ===")
    out = _roundtrip(f'fetch("{pdb}", True)', host, port, timeout_ms=ZMQ_TIMEOUT_MS_FETCH)
    print(_fmt(out))

    info = _poll_until_loaded(host, port)
    if info.get("ok", False):
        print(f"Loaded evidence via {info.get('source')}.")
        return True

    print("\n=== FETCH (mmCIF=False) ===")
    out = _roundtrip(f'fetch("{pdb}", False)', host, port, timeout_ms=ZMQ_TIMEOUT_MS_FETCH)
    print(_fmt(out))

    info = _poll_until_loaded(host, port)
    if info.get("ok", False):
        print(f"Loaded evidence via {info.get('source')}.")
        return True

    print("\n=== RCSB loadFromString fallback ===")
    try:
        data = _download_rcsb(pdb, fmt="pdb")
    except Exception as e:
        print(f"RCSB download failed: {e}")
        return False

    # Try 2-arg loadFromString first, then a common extended signature.
    cmd1 = f'loadFromString("{pdb}.pdb", {json.dumps(data)})'
    out1 = _roundtrip(cmd1, host, port, timeout_ms=ZMQ_TIMEOUT_MS_LOADSTR)
    print("loadFromString(2-arg):", _fmt(out1))

    if not _ok(out1):
        cmd2 = (
            f'loadFromString("{pdb}.pdb", {json.dumps(data)}, '
            "True, False, True, True, True, -1)"
        )
        out2 = _roundtrip(cmd2, host, port, timeout_ms=ZMQ_TIMEOUT_MS_LOADSTR)
        print("loadFromString(extended):", _fmt(out2))

    info = _poll_until_loaded(host, port)
    if info.get("ok", False):
        print(f"Loaded evidence via {info.get('source')}.")
        return True

    print("\nNo evidence after RCSB fallback either.")
    return False


def main() -> None:
    host = os.environ.get("UMOL_HOST") or "localhost"
    port = int(os.environ.get("UMOL_PORT", "5555"))

    # Prefer a tiny structure for reliability; override with UMOL_PROBE_PDB if needed.
    requested = os.environ.get("UMOL_PROBE_PDB", "1crn").strip()

    if not requested:
        print("Empty UMOL_PROBE_PDB / requested PDB id.")
        return

    ok = _try_robust_load(host, port, requested)
    if not ok:
        # Print last-known lists for debugging.
        print("\n=== FINAL STATE ===")
        s1 = _roundtrip("getStructureListString()", host, port, ZMQ_TIMEOUT_MS_DEFAULT)
        s2 = _roundtrip("getSelectionListString()", host, port, ZMQ_TIMEOUT_MS_DEFAULT)
        print("getStructureListString():", _fmt(s1))
        print("getSelectionListString():", _fmt(s2))
        print("\nThis usually means your UnityMol build/session isn't actually loading structures via ZMQ.")
        return

    sel_name = f"all_{requested.lower()}"

    print("\n=== ENSURE SELECTION EXISTS ===")
    mk = _roundtrip(f'select("all", "{sel_name}")', host, port, timeout_ms=8000)
    print(f'select("all","{sel_name}") ->', _fmt(mk))
    if not _ok(mk):
        print("\nSelection creation failed. Aborting rep/color probes.")
        return

    print("\n=== SELECTIONS (after select) ===")
    sel2 = _roundtrip("getSelectionListString()", host, port, timeout_ms=ZMQ_TIMEOUT_MS_DEFAULT)
    print(_fmt(sel2))

    # 1) Probe showSelection rep types (strings)
    reps = [
        "c",        # cartoon
        "hb",       # hyperball
        "l",        # lines
        "s",        # surface
        "p",        # points
        "trace",
        "sphere",
        "bondorder",
        "hbond",
        "hbondtubes",
    ]

    print("\n=== showSelection probes ===")
    good_reps: List[str] = []
    for rep in reps:
        cmd = f'showSelection("{sel_name}", "{rep}")'
        out = _roundtrip(cmd, host, port, timeout_ms=ZMQ_TIMEOUT_MS_DEFAULT)
        ok2 = _ok(out)
        stdout = (out.get("stdout", "") or "").replace("\r", "")
        tag = "[OK]" if ok2 else "[NO]"
        print(f"{tag} {cmd:60} result={out.get('result','')!r} stdout={stdout[:120]!r}")
        if ok2:
            good_reps.append(rep)
        time.sleep(0.05)

    if not good_reps:
        print("\nNo rep type succeeded (with clean stdout).")
        return

    # 2) Probe colorSelection arguments
    print("\n=== colorSelection probes ===")
    print('NOTE: we try string colors first: colorSelection(sel, rep, "red")\n')

    named_colors = ["red", "green", "blue", "white", "yellow"]
    color_exprs = [
        '__import__("UnityEngine").Color.red',
        '__import__("UnityEngine").Color(1.0,0.0,0.0,1.0)',
        "UnityEngine.Color.red",
        "UnityEngine.Color(1.0,0.0,0.0,1.0)",
        "Color.red",
        "Color(1.0,0.0,0.0,1.0)",
    ]

    for rep in good_reps:
        for name in named_colors:
            cmd = f'colorSelection("{sel_name}", "{rep}", "{name}")'
            out = _roundtrip(cmd, host, port, timeout_ms=ZMQ_TIMEOUT_MS_DEFAULT)
            ok2 = _ok(out)
            stdout = (out.get("stdout", "") or "").replace("\r", "")
            tag = "[OK]" if ok2 else "[NO]"
            print(f"{tag} rep={rep:<10} arg={name!r:<10} result={out.get('result','')!r} stdout={stdout[:120]!r}")
            time.sleep(0.05)

        for expr in color_exprs:
            cmd = f'colorSelection("{sel_name}", "{rep}", {expr})'
            out = _roundtrip(cmd, host, port, timeout_ms=ZMQ_TIMEOUT_MS_DEFAULT)
            ok2 = _ok(out)
            stdout = (out.get("stdout", "") or "").replace("\r", "")
            tag = "[OK]" if ok2 else "[NO]"
            print(f"{tag} rep={rep:<10} expr={expr:<55} result={out.get('result','')!r} stdout={stdout[:120]!r}")
            time.sleep(0.05)

    # 3) Optional: probe colorBy* schemes
    print("\n=== colorBy* scheme probes (optional) ===")
    schemes = ["colorByAtom", "colorByResidue", "colorByChain"]
    for rep in good_reps:
        for fn in schemes:
            cmd = f'{fn}("{sel_name}", "{rep}")'
            out = _roundtrip(cmd, host, port, timeout_ms=10000)
            ok2 = _ok(out)
            stdout = (out.get("stdout", "") or "").replace("\r", "")
            tag = "[OK]" if ok2 else "[NO]"
            print(f"{tag} {cmd:50} result={out.get('result','')!r} stdout={stdout[:120]!r}")
            time.sleep(0.05)


if __name__ == "__main__":
    main()

