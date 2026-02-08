#!/usr/bin/env python3
"""Probe UnityMol ZMQ for introspection calls (safe, no hangs)."""

import json
import os
import zmq

HOST = os.environ.get("UMOL_HOST", "localhost")
PORT = int(os.environ.get("UMOL_PORT", "5555"))
TIMEOUT_MS = 800

CANDIDATES = [
    # selections
    "getSelectionListString()",
    "getCurrentSelectionName()",
    "getCurrentSelection()",

    # structures / molecules
    "getMoleculeListString()",
    "getLoadedMolecules()",
    "getStructureListString()",
    "getAllMolecules()",

    # representations
    "getRepresentationListString()",
    "getRepListString()",
    "getAllRepListString()",
    "getVisibleRepListString()",
]


def call(cmd: str) -> dict:
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, TIMEOUT_MS)
    sock.setsockopt(zmq.SNDTIMEO, TIMEOUT_MS)
    sock.connect(f"tcp://{HOST}:{PORT}")
    try:
        sock.send_string(cmd)
        raw = sock.recv().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"success": False, "result": "", "stdout": raw}
    except Exception as e:
        return {"success": False, "result": "", "stdout": f"[timeout/error] {e}"}
    finally:
        sock.close()


def main():
    print(f"Probing {HOST}:{PORT} (timeout {TIMEOUT_MS}ms)\n")
    for cmd in CANDIDATES:
        out = call(cmd)
        ok = out.get("success", False)
        res = out.get("result", "")
        preview = str(res)
        if len(preview) > 140:
            preview = preview[:140] + "..."
        status = "OK" if ok else "NO"
        print(f"[{status}] {cmd:<28} result_preview={preview}")
        if (not ok) and out.get("stdout"):
            # show first line only
            print("      err:", str(out["stdout"]).splitlines()[0][:160])


if __name__ == "__main__":
    main()

