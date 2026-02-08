#!/usr/bin/env python3
"""Scene Context Tree builder for UnityMolX (safe, versioned, compact).

Goal:
- Provide a compact JSON snapshot of the current UnityMol scene:
  structures, selections, representations (tracked from actions), plus recent actions.
- Must NEVER hang if a UnityMol API call is missing/invalid.

Approach:
- Use raw pyzmq roundtrips with RCVTIMEO/SNDTIMEO for introspection calls.
- Prefer known-stable calls (getSelectionListString).
- Optionally try getStructureListString if available (some builds expose it).
- Infer structure *instances* from `all_*` selections (e.g. all_1kx2_2).
- Use recent_actions (with actual 'result') to pick the active instance reliably.
- Track representations + colors by parsing executed commands in recent_actions.

Step 2 fixes:
- Parse colorSelection(sel, repType, ColorExpr) correctly (repType, not "atom/residue/all").
- Attach color to that specific (sel, repType) rep.
- Parse optional colorBy* scheme calls.
- IGNORE failed actions (success=False) so context doesn't learn from warnings/errors.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple


ZMQ_TIMEOUT_MS = 800

_PDB4 = re.compile(r"^([A-Za-z0-9]{4})(?:_|$)")

_RE_SHOW = re.compile(r'showSelection\("(?P<sel>[^"]+)",\s*"(?P<rep>[^"]+)"')
# Some builds may support hideSelection(sel, repType); most use hideSelection(sel).
_RE_HIDE = re.compile(r'hideSelection\("(?P<sel>[^"]+)"(?:,\s*"(?P<rep>[^"]+)")?\)')
_RE_COLOR = re.compile(
    r'colorSelection\("(?P<sel>[^"]+)",\s*"(?P<rep>[^"]+)",\s*(?P<expr>.+)\)\s*$'
)
_RE_COLOR_BY = re.compile(
    r'colorBy(?P<scheme>Atom|Residue|Chain|Hydrophobicity|Sequence|Charge|ResidueType|ResidueCharge|Bfactor)\("(?P<sel>[^"]+)",\s*"(?P<rep>[^"]+)"\)\s*$'
)

_RE_COLOR_CALL = re.compile(
    r'Color\(\s*(?P<r>[-0-9.eE]+)\s*,\s*(?P<g>[-0-9.eE]+)\s*,\s*(?P<b>[-0-9.eE]+)\s*,\s*(?P<a>[-0-9.eE]+)\s*\)'
)
_RE_COLOR_DOT = re.compile(r"Color\.(?P<name>[A-Za-z_]+)\b")


def _stdout_has_problem(stdout: str) -> bool:
    s = (stdout or "").replace("\r", "")
    return ("[Warning]" in s) or ("[Error]" in s)


def _effective_success(payload: Dict[str, Any]) -> bool:
    if not bool(payload.get("success", False)):
        return False
    if _stdout_has_problem(payload.get("stdout", "") or ""):
        return False
    return True


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


def _parse_listish(value: Any) -> List[str]:
    """Parse UnityMol list-ish results robustly."""
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

    # Bracketed comma-separated list: [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()]
        return [p for p in parts if p]

    # Fallback: newline-separated
    return [ln.strip() for ln in s.splitlines() if ln.strip()]


def _structures_from_all_selections(selection_names: list[str]) -> list[str]:
    """Return structure *instance* names inferred from all_* selections."""
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
    """Infer (active_structure_instance, active_selection_name) from most recent successful action."""
    if not recent_actions:
        return None, None

    for a in reversed(recent_actions):
        args = a.get("args", {}) or {}
        if not bool(args.get("success", True)):
            # ignore failed/warning actions
            continue

        cmd = str(args.get("command", "") or "")
        res = args.get("result", "")

        m = re.search(r'select\("all",\s*"(?P<sel>all_[^"]+)"', cmd)
        if m:
            sel = m.group("sel")
            inst = sel[len("all_") :] if sel.startswith("all_") else None
            return inst, sel

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

    if active_struct is None and structures_from_sel:
        active_struct = structures_from_sel[-1]

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


def _palette() -> Dict[str, List[float]]:
    """Shared palette for parsing and for context display."""
    return {
        "red": [1.0, 0.0, 0.0, 1.0],
        "green": [0.0, 1.0, 0.0, 1.0],
        "blue": [0.0, 0.0, 1.0, 1.0],
        "white": [1.0, 1.0, 1.0, 1.0],
        "black": [0.0, 0.0, 0.0, 1.0],
        "yellow": [1.0, 1.0, 0.0, 1.0],
        "cyan": [0.0, 1.0, 1.0, 1.0],
        "magenta": [1.0, 0.0, 1.0, 1.0],
        "orange": [1.0, 0.5, 0.0, 1.0],
        "gray": [0.5, 0.5, 0.5, 1.0],
        "grey": [0.5, 0.5, 0.5, 1.0],
    }


def _rgba_from_expr(expr: str) -> Optional[List[float]]:
    """Best-effort parse RGBA from a colorSelection third argument expression."""
    s = (expr or "").strip()

    m = _RE_COLOR_CALL.search(s)
    if m:
        try:
            return [
                float(m.group("r")),
                float(m.group("g")),
                float(m.group("b")),
                float(m.group("a")),
            ]
        except Exception:
            return None

    m = _RE_COLOR_DOT.search(s)
    if m:
        name = m.group("name").lower()
        return _palette().get(name)

    return None


def _representations_from_actions(
    recent_actions: List[dict],
    selection_names: List[str],
) -> List[dict]:
    """Infer representation state from executed commands in recent_actions (successful actions only)."""
    reps_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    rep_id_counter = 0

    def _ensure_rep(sel: str, rep_type: str, t: float) -> Dict[str, Any]:
        nonlocal rep_id_counter
        key = (sel, rep_type)
        if key not in reps_by_key:
            rep_id = f"rep{rep_id_counter}"
            rep_id_counter += 1

            inst = sel[len("all_") :] if sel.startswith("all_") else None
            reps_by_key[key] = {
                "rep_id": rep_id,
                "selection_name": sel,
                "structure_instance": inst,
                "rep_type": rep_type,
                "visible": True,
                "color": None,
                "last_updated": t,
                "source": "recent_actions",
            }
            order.append(key)
        return reps_by_key[key]

    for a in recent_actions or []:
        args = a.get("args", {}) or {}
        if not bool(args.get("success", True)):
            continue

        cmd = str(args.get("command", "") or "")
        t = float(a.get("t", 0.0) or 0.0)

        m = _RE_SHOW.search(cmd)
        if m:
            sel = m.group("sel")
            rep_type = m.group("rep")
            rep = _ensure_rep(sel, rep_type, t)
            rep["visible"] = True
            rep["last_updated"] = t
            continue

        m = _RE_HIDE.search(cmd)
        if m:
            sel = m.group("sel")
            rep_type = m.groupdict().get("rep")

            if rep_type:
                rep = _ensure_rep(sel, rep_type, t)
                rep["visible"] = False
                rep["last_updated"] = t
            else:
                found = False
                for (s, _r), rep in reps_by_key.items():
                    if s == sel:
                        rep["visible"] = False
                        rep["last_updated"] = t
                        found = True
                if not found:
                    rep = _ensure_rep(sel, "__unknown__", t)
                    rep["visible"] = False
                    rep["last_updated"] = t
            continue

        m = _RE_COLOR.search(cmd)
        if m:
            sel = m.group("sel")
            rep_type = m.group("rep")
            expr = m.group("expr")
            rgba = _rgba_from_expr(expr)

            rep = _ensure_rep(sel, rep_type, t)
            rep["color"] = {
                "scheme": "constant",
                "rgba": rgba,
                "expr": str(expr).strip(),
            }
            rep["last_updated"] = t
            continue

        m = _RE_COLOR_BY.search(cmd)
        if m:
            sel = m.group("sel")
            rep_type = m.group("rep")
            scheme = (m.group("scheme") or "").lower()

            rep = _ensure_rep(sel, rep_type, t)
            rep["color"] = {"scheme": f"by_{scheme}"}
            rep["last_updated"] = t
            continue

    if selection_names:
        filtered: List[Tuple[str, str]] = [k for k in order if k[0] in selection_names]
    else:
        filtered = order

    return [reps_by_key[k] for k in filtered]


def build_scene_context(unitymol: Any, recent_actions: list[dict], compact: bool = True) -> dict:
    """Build Scene Context Tree v1 (safe, minimal, but active-correct + rep-tracking)."""
    now = time.time()

    # Introspection calls we know often work
    sel_payload = _call(unitymol, "getSelectionListString()")
    has_sel_list = _effective_success(sel_payload)
    selection_names = _parse_listish(sel_payload.get("result")) if has_sel_list else []

    # Optional structure list if available in this build
    struct_payload = _call(unitymol, "getStructureListString()")
    has_struct_list = _effective_success(struct_payload)
    structure_list = _parse_listish(struct_payload.get("result")) if has_struct_list else []

    # Structures inferred from all_* selections (keeps instance names like 1kx2_2)
    structures_from_sel = _structures_from_all_selections(selection_names)
    structures_in_scene = structures_from_sel if structures_from_sel else structure_list

    # Active inference
    active_struct, active_sel = _pick_active(selection_names, structures_in_scene, recent_actions or [])

    # Representations inferred from successful recent actions
    representations = _representations_from_actions(list(recent_actions or []), selection_names)

    # Active rep ids: reps for active selection that are visible
    active_rep_ids: List[str] = []
    if active_sel:
        for rep in representations:
            if rep.get("selection_name") == active_sel and rep.get("visible", False):
                rid = rep.get("rep_id")
                if isinstance(rid, str):
                    active_rep_ids.append(rid)

    # Structures list
    structures: list[dict] = []
    for i, inst in enumerate(structures_in_scene):
        inst_s = str(inst)
        structures.append(
            {
                "structure_id": f"s{i}",
                "name": inst_s,
                "source": {
                    "type": "pdb",
                    "requested": _requested_from_instance(inst_s),
                    "loaded": inst_s,
                },
            }
        )

    # Selections list
    selections: list[dict] = []
    for i, name in enumerate(selection_names):
        hint = _requested_from_instance(name[len("all_") :]) if name.startswith("all_") else _requested_from_instance(name)
        selections.append(
            {
                "selection_id": f"sel{i}",
                "name": name,
                "structure_hint": hint,
            }
        )

    ctx = {
        "schema": "unitymolx.scene_context.v1",
        "timestamp": now,
        "active": {
            "structure_name": active_struct,
            "selection_name": active_sel,
            "rep_ids": active_rep_ids,
        },
        "structures": structures,
        "selections": selections,
        "representations": representations,
        "styles": {"palette": _palette()},
        "recent_actions": list(recent_actions or []),
        "capabilities": {
            "has_selection_list": has_sel_list,
            "has_structure_list": has_struct_list,
            "has_rep_introspection": False,
            "has_rep_tracking": True,
        },
    }

    if not compact:
        ctx["introspection"] = {
            "getSelectionListString": sel_payload,
            "getStructureListString": struct_payload,
        }

    return ctx

