#!/usr/bin/env python3
"""Scene Context Tree builder for UnityMolX (safe, versioned, compact).

Goal:
- Provide a compact JSON snapshot of the current UnityMol scene:
  structures, selections, (later) representations, plus recent actions.
- Must NEVER hang if a UnityMol API call is missing/invalid.

Approach:
- Use raw pyzmq roundtrips with RCVTIMEO/SNDTIMEO for introspection calls.
- Prefer known-stable calls (getSelectionListString).
- Infer structure *instances* from `all_*` selections (e.g. all_1kx2_2).
- Use recent_actions (with actual 'result') to pick the active instance reliably.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any


ZMQ_TIMEOUT_MS = 800
_PDB4 = re.compile(r"^([A-Za-z0-9]{4})(?:_|$)")


def _zmq_roundtrip(host: str, port: int, command: str, timeout_ms: int = ZMQ_TIMEOUT_MS) -> dict:
    """Send one command over a fresh ZMQ REQ socket with timeouts; return parsed JSON or error."""
    import zmq

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
            # UnityMol should return JSON; if not, preserve raw
            return {"success": False, "result": "", "stdout": raw}
    except Exception as e:
        return {"success": False, "result": "", "stdout": f"[timeout/error] {e}"}
    finally:
        sock.close()


def _get_host_port(unitymol: Any) -> tuple[str, int]:
    """Derive host/port from UnityMolZMQ client or environment."""
    host = getattr(unitymol, "host", None) or os.environ.get("UMOL_HOST", "localhost")
    port = getattr(unitymol, "port", None) or int(os.environ.get("UMOL_PORT", "5555"))
    return str(host), int(port)


def _call(unitymol: Any, cmd: str) -> dict:
    """Safe UnityMol call that cannot hang. Returns UnityMol JSON payload directly."""
    host, port = _get_host_port(unitymol)
    return _zmq_roundtrip(host, port, cmd)


def _parse_sel_list(sel_result: Any) -> list[str]:
    """Parse UnityMol getSelectionListString() result into a list of selection names.

    Observed formats:
      - "[]"
      - "[all_1kx2, 1kx2_protein_or_nucleic, ...]"
      - JSON list string: '["all_1kx2", ...]' (rare)
      - newline-separated (fallback)

    Returns a list of strings, preserving order.
    """
    if sel_result is None:
        return []

    if isinstance(sel_result, list):
        return [str(x).strip() for x in sel_result if str(x).strip()]

    s = str(sel_result).strip()
    if not s or s == "[]":
        return []

    # JSON list string
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass

    # Bracketed comma-separated list: [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        return [p.strip().strip('"').strip("'") for p in parts if p.strip()]

    # Fallback: newline-separated
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def _structures_from_all_selections(selection_names: list[str]) -> list[str]:
    """Return structure *instance* names inferred from all_* selections.

    Examples:
      all_1kx2      -> "1kx2"
      all_1kx2_2    -> "1kx2_2"
      all_5iuf      -> "5iuf"

    Order preserved as encountered in selection list.
    """
    seen: set[str] = set()
    out: list[str] = []
    for name in selection_names:
        if name.startswith("all_") and len(name) > 4:
            inst = name[len("all_") :].strip()
            if inst and inst not in seen:
                seen.add(inst)
                out.append(inst)
    return out


def _active_from_recent_actions(recent_actions: list[dict]) -> tuple[str | None, str | None]:
    """Infer (active_structure_instance, active_selection_name) from most recent meaningful action.

    Uses RECENT_ACTIONS entries produced by mcp_server.py, where args include:
      { "command": "...", "success": bool, "result": "..."}
    """
    if not recent_actions:
        return None, None

    for a in reversed(recent_actions):
        args = a.get("args", {}) or {}
        cmd = str(args.get("command", "") or "")
        res = args.get("result", "")

        # If the last action was selecting "all" into a named all_* selection,
        # that's strong evidence of active structure + selection.
        m = re.search(r'select\("all",\s*"(?P<sel>all_[^"]+)"', cmd)
        if m:
            sel = m.group("sel")
            inst = sel[len("all_") :] if sel.startswith("all_") else None
            return inst, sel

        # If the last action was a fetch, UnityMol returns the loaded instance in result:
        # fetch("1kx2") -> result "1kx2_2" when duplicated (sometimes)
        m = re.search(r'fetch\("([^"]+)"\)', cmd)
        if m:
            if isinstance(res, str) and res.strip() and res.strip() != "[]":
                inst = res.strip()
                return inst, f"all_{inst}"
            req = m.group(1).strip()
            return req, f"all_{req}"

    return None, None


def _pick_active(
    selection_names: list[str],
    structures_from_sel: list[str],
    recent_actions: list[dict],
) -> tuple[str | None, str | None]:
    """Pick active (structure_instance, selection_name) with robust fallbacks."""
    active_struct, active_sel = _active_from_recent_actions(recent_actions)

    # If actions didn't tell us, fall back to last all_* structure instance (most recent loaded)
    if active_struct is None and structures_from_sel:
        active_struct = structures_from_sel[-1]

    # If selection isn't set, prefer all_<active_struct> if it exists
    if active_sel is None:
        if active_struct is not None:
            candidate = f"all_{active_struct}"
            if candidate in selection_names:
                active_sel = candidate
        if active_sel is None and selection_names:
            active_sel = selection_names[0]

    return active_struct, active_sel


def _requested_from_instance(inst: str) -> str:
    """Map an instance name (e.g., 1kx2_2) -> requested base code (e.g., 1kx2)."""
    m = _PDB4.match(inst)
    return m.group(1).lower() if m else inst.lower()


def build_scene_context(unitymol: Any, recent_actions: list[dict], compact: bool = True) -> dict:
    """Build Scene Context Tree v1 (safe, minimal, but active-correct)."""
    now = time.time()

    # Introspection calls we know work
    sel_payload = _call(unitymol, "getSelectionListString()")
    selection_names = _parse_sel_list(sel_payload.get("result"))

    # Structures inferred from all_* selections (keeps instance names like 1kx2_2)
    structures_from_sel = _structures_from_all_selections(selection_names)

    # Active inference
    active_struct, active_sel = _pick_active(selection_names, structures_from_sel, recent_actions or [])

    # Structures list
    structures: list[dict] = []
    for i, inst in enumerate(structures_from_sel):
        structures.append(
            {
                "structure_id": f"s{i}",
                "name": inst,  # instance: 1kx2_2
                "source": {
                    "type": "pdb",
                    "requested": _requested_from_instance(inst),
                    "loaded": inst,
                },
            }
        )

    # Selections list (include a structure_hint if a selection begins with a pdb4)
    selections: list[dict] = []
    for i, name in enumerate(selection_names):
        if name.startswith("all_"):
            hint = _requested_from_instance(name[len("all_") :])
        else:
            hint = _requested_from_instance(name)
        selections.append(
            {
                "selection_id": f"sel{i}",
                "name": name,
                "structure_hint": hint,
            }
        )

    # Representations: fill once we discover a working rep introspection API.
    representations: list[dict] = []

    ctx = {
        "schema": "unitymolx.scene_context.v1",
        "timestamp": now,
        "active": {
            "structure_name": active_struct,
            "selection_name": active_sel,
            "rep_ids": [],
        },
        "structures": structures,
        "selections": selections,
        "representations": representations,
        "styles": {
            "palette": {
                "red": [1, 0, 0, 1],
                "green": [0, 1, 0, 1],
                "blue": [0, 0, 1, 1],
                "white": [1, 1, 1, 1],
            }
        },
        "recent_actions": list(recent_actions or []),
        "capabilities": {
            "has_selection_list": bool(sel_payload.get("success", False)),
            "has_rep_introspection": False,
            "has_structure_introspection": False,
        },
    }

    if not compact:
        ctx["introspection"] = {
            "getSelectionListString": sel_payload,
        }

    return ctx

