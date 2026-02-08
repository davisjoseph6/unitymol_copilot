#!/usr/bin/env python3
"""List UnityMol global symbols matching a keyword (safe)."""

import os
import json
import zmq

HOST = os.environ.get("UMOL_HOST", "localhost")
PORT = int(os.environ.get("UMOL_PORT", "5555"))
TIMEOUT_MS = 1200

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
        return json.loads(raw)
    except Exception as e:
        return {"success": False, "result": "", "stdout": f"[timeout/error] {e}"}
    finally:
        sock.close()

def main():
    queries = [
        '"|".join([n for n in dir() if "rep" in n.lower()])',
        '"|".join([n for n in dir() if "show" in n.lower() and "sel" in n.lower()])',
        '"|".join([n for n in dir() if "color" in n.lower()])',
        '"|".join([n for n in dir() if "mol" in n.lower() or "struct" in n.lower()])',
    ]
    for q in queries:
        out = call(q)
        print("\nQUERY:", q)
        print("OK:", out.get("success"), "RESULT:", str(out.get("result", ""))[:200])

if __name__ == "__main__":
    main()

