#!/usr/bin/env python3
"""Probe UnityMol ZMQ for available introspection commands.

This script sends a list of candidate UnityMol API calls through ZMQ and
reports which ones succeed and what the returned type looks like.
"""

import json
from unitymol_zmq import UnityMolZMQ

CANDIDATES = [
    "ls()",
    "getSelectionListString()",
    "getSelectionList()",
    "getCurrentSelectionName()",
    "getCurrentSelection()",
    "getLoadedMolecules()",
    "getMoleculeListString()",
    "getAllMolecules()",
    "getStructureListString()",
    "getStructureList()",
    "getRepresentationListString()",
    "getRepListString()",
    "getAllRepListString()",
    "getVisibleRepListString()",
    "getCamera()",
]


def _try_parse(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


def main():
    u = UnityMolZMQ(host="localhost", port=5555)
    if not u.connect():
        raise SystemExit("ERROR: could not connect to UnityMol ZMQ on localhost:5555")

    print("Connected.\n")

    for cmd in CANDIDATES:
        try:
            out = u.send_command(cmd)
            parsed = _try_parse(out)
            kind = type(parsed).__name__
            preview = str(parsed)
            if len(preview) > 180:
                preview = preview[:180] + "..."
            print(f"[OK] {cmd:<30} type={kind:<12} preview={preview}")
        except Exception as e:
            print(f"[NO] {cmd:<30} err={e}")


if __name__ == "__main__":
    main()

