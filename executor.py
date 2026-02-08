#!/usr/bin/env python3
"""
unitymol_copilot.executor

Map a validated DSL AST to a list of UnityMol ZMQ command strings.

Step 0 robustness:
- Use __LOAD_STRUCTURE__("1crn") directive, intercepted by mcp_server.py

Step 2 robustness:
- Use __COLOR_SELECTION__("all_1crn", "c", "red") directive, intercepted by mcp_server.py

QoL:
- Normalize common rep names (e.g. "cartoon" -> "c") so DSL can stay friendly.
"""

from __future__ import annotations

import re
from pathlib import Path


def _esc(s: str) -> str:
    """Escape for inclusion inside double-quoted UnityMol command strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _norm_path(p: str) -> str:
    """Unity/Mono on Windows is fine with forward slashes; normalize for safety."""
    return p.replace("\\", "/")


def _normalize_rep_type(rep_type: str) -> str:
    """Keep DSL friendly; map to UnityMol repType codes when obvious."""
    t = (rep_type or "").strip().lower()
    mapping = {
        "cartoon": "c",
        "c": "c",
        "hyperball": "hb",
        "hb": "hb",
        "line": "l",
        "lines": "l",
        "l": "l",
        "surface": "s",
        "s": "s",
        "trace": "trace",
        "points": "p",
        "point": "p",
        "p": "p",
        # allow pass-through for other names:
        "sphere": "sphere",
        "bondorder": "bondorder",
        "hbond": "hbond",
        "hbondtubes": "hbondtubes",
        "tube": "tube",
        "atom": "atom",
        "bond": "bond",
    }
    return mapping.get(t, (rep_type or "").strip())


def dsl_to_zmq_calls(ast):
    """
    Map validated DSL AST to a list of UnityMol ZMQ command strings.
    """
    cmds = []

    for node in ast:
        s = node["stmt"]
        a = node["args"]

        if s == "add_structure":
            if "PDBID" in a:
                pdbid = a["PDBID"].lower()

                # Robust loader directive handled by mcp_server.py (NOT sent to UnityMol directly).
                cmds.append(f'__LOAD_STRUCTURE__("{_esc(pdbid)}")')

                # IMPORTANT:
                # The server will ensure an alias selection exists named all_<pdbid>.
                # So downstream DSL can safely refer to all_1crn.
                # (This is created after actual load evidence appears.)
            elif "filePath" in a:
                path = _norm_path(a["filePath"])
                cmds.append(f'load("{_esc(path)}")')

                # Convenience selection if filename stem looks like a PDB id.
                stem = Path(path).stem.lower()
                if re.fullmatch(r"[0-9][a-z0-9]{3}", stem):
                    sel = f"all_{stem}"
                    cmds.append(f'select("all", "{_esc(sel)}", True, False, True)')
            else:
                raise ValueError("add_structure requires PDBID or filePath")

        elif s == "select":
            query = _esc(a["query"])
            name = _esc(a.get("name", "selection"))
            cmds.append(f'select("{query}", "{name}", True, False, True)')

        elif s == "show":
            sel = _esc(a["sel"])
            rep = _esc(_normalize_rep_type(a["rep"]))
            cmds.append(f'showSelection("{sel}", "{rep}")')

        elif s == "hide":
            sel = _esc(a["sel"])
            cmds.append(f'hideSelection("{sel}")')

        elif s == "color_by_chain":
            sel = _esc(a["sel"])
            target = _esc(_normalize_rep_type(a["target"]))
            cmds.append(f'colorByChain("{sel}", "{target}")')

        # Step 2: robust color in DSL execution via server-intercepted directive.
        # Support both stmt names to be safe across grammar variants.
        elif s in ("color_selection", "color"):
            sel = a.get("sel") or a.get("selection") or a.get("selection_name") or a.get("name")
            rep = a.get("rep") or a.get("rep_type") or a.get("target")
            col = a.get("color") or a.get("col") or a.get("value")

            if not sel or not rep or not col:
                raise ValueError("color/color_selection requires sel, rep, and color")

            rep_norm = _normalize_rep_type(str(rep))
            cmds.append(
                f'__COLOR_SELECTION__("{_esc(str(sel))}", "{_esc(rep_norm)}", "{_esc(str(col))}")'
            )

        else:
            raise NotImplementedError(s)

    return cmds

