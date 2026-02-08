#!/usr/bin/env python3
"""
unitymol_copilot.validator

Strict molcommand DSL grammar + validation.

Step 2 requirement:
- Support color statements in the DSL so robust coloring can be exercised through:
    color(sel="all_1crn", rep="cartoon", color="red")
  or
    color_selection(sel="all_1crn", rep="c", color="red")

Notes:
- We validate structure IDs, selection names, and rep targets (friendly names + codes).
- We do not over-validate color strings; they are forwarded to the server which
  tries multiple encodings (string name then UnityEngine.Color fallback).
"""

from __future__ import annotations

import re
from lark import Lark, Transformer, v_args

GRAMMAR = r"""
start: stmt+

?stmt: add_structure
     | select_stmt
     | show_stmt
     | hide_stmt
     | color_by_chain_stmt
     | color_stmt
     | color_selection_stmt

# ---- add_structure ----
add_structure : "add_structure" "(" add_args ")"
add_args      : pdbid_arg | file_arg
pdbid_arg     : "PDBID" "=" ESCAPED_STRING      -> arg_pdbid
file_arg      : "filePath" "=" ESCAPED_STRING   -> arg_file

# ---- select ----
select_stmt   : "select" "(" "query" "=" ESCAPED_STRING ("," "name" "=" ESCAPED_STRING)? ")"

# ---- show/hide ----
show_stmt     : "show" "(" "sel" "=" ESCAPED_STRING "," "rep" "=" ESCAPED_STRING ")"
hide_stmt     : "hide" "(" "sel" "=" ESCAPED_STRING ")"

# ---- color_by_chain ----
color_by_chain_stmt : "color_by_chain" "(" "sel" "=" ESCAPED_STRING "," "target" "=" ESCAPED_STRING ")"

# ---- Step 2: color (robust) ----
color_stmt : "color" "(" "sel" "=" ESCAPED_STRING "," "rep" "=" ESCAPED_STRING "," "color" "=" ESCAPED_STRING ")"
color_selection_stmt : "color_selection" "(" "sel" "=" ESCAPED_STRING "," "rep" "=" ESCAPED_STRING "," "color" "=" ESCAPED_STRING ")"

%import common.ESCAPED_STRING
%import common.WS_INLINE
%import common.NEWLINE
SEMI: ";"

%ignore WS_INLINE
%ignore NEWLINE
%ignore SEMI
"""

_parser = Lark(GRAMMAR, start="start", maybe_placeholders=False)


def _unq(tok) -> str:
    """Unquote a Lark ESCAPED_STRING token into a raw python string."""
    s = str(tok)  # ESCAPED_STRING like '"abc"'
    return s[1:-1]


@v_args(inline=True)
class BuildAST(Transformer):
    def start(self, *stmts):
        return list(stmts)

    # --- add_structure ---
    def arg_pdbid(self, s):
        return ("PDBID", _unq(s))

    def arg_file(self, s):
        return ("filePath", _unq(s))

    def add_args(self, *pairs):
        return {k: v for (k, v) in pairs}

    def add_structure(self, args):
        return {"stmt": "add_structure", "args": args}

    # --- select ---
    def select_stmt(self, q, *maybe_name):
        name = _unq(maybe_name[0]) if maybe_name else "selection"
        return {"stmt": "select", "args": {"query": _unq(q), "name": name}}

    # --- show/hide ---
    def show_stmt(self, sel, rep):
        return {"stmt": "show", "args": {"sel": _unq(sel), "rep": _unq(rep)}}

    def hide_stmt(self, sel):
        return {"stmt": "hide", "args": {"sel": _unq(sel)}}

    # --- color_by_chain ---
    def color_by_chain_stmt(self, sel, target):
        return {"stmt": "color_by_chain", "args": {"sel": _unq(sel), "target": _unq(target)}}

    # --- Step 2: color ---
    def color_stmt(self, sel, rep, col):
        return {"stmt": "color", "args": {"sel": _unq(sel), "rep": _unq(rep), "color": _unq(col)}}

    def color_selection_stmt(self, sel, rep, col):
        return {"stmt": "color_selection", "args": {"sel": _unq(sel), "rep": _unq(rep), "color": _unq(col)}}


def parse_and_validate_molcommand(program: str):
    """
    Parse a molcommand script and return (ok: bool, ast: list[dict] | None, errors: list[str]).
    """
    try:
        tree = _parser.parse(program)
        ast = BuildAST().transform(tree)  # list[dict]

        errors = []

        # Friendly rep names + common codes
        allowed_rep_targets = {
            # friendly
            "cartoon", "hyperball", "line", "lines", "surface", "trace", "points",
            # codes
            "c", "hb", "l", "s", "p", "trace",
            # allow some additional UnityMol-ish strings that appear in builds
            "sphere", "bondorder", "hbond", "hbondtubes",
            # for color_by_chain in your earlier validator style:
            "atom", "bond", "tube", "point",
        }

        for node in ast:
            stmt = node.get("stmt")
            args = node.get("args", {})

            if stmt == "add_structure":
                has_pdb = "PDBID" in args
                has_file = "filePath" in args
                if has_pdb == has_file:
                    errors.append("add_structure requires exactly one of PDBID or filePath")
                if has_pdb:
                    pdb = args["PDBID"].strip()
                    if not re.fullmatch(r"[0-9][A-Za-z0-9]{3}", pdb):
                        errors.append(f"Invalid PDB ID: {pdb}")
                if has_file and not args["filePath"].strip():
                    errors.append("filePath must be non-empty")

            elif stmt == "select":
                q = args.get("query", "").strip()
                name = args.get("name", "").strip()
                if not q:
                    errors.append("select.query must be non-empty")
                if not name:
                    errors.append("select.name must be non-empty")
                if any(ch in name for ch in ['"', "\n", "\r", "\t"]):
                    errors.append(f'select.name contains invalid characters: {name!r}')

            elif stmt == "show":
                if not args.get("sel", "").strip():
                    errors.append("show.sel must be non-empty")
                rep = args.get("rep", "").strip()
                if not rep:
                    errors.append("show.rep must be non-empty")

            elif stmt == "hide":
                if not args.get("sel", "").strip():
                    errors.append("hide.sel must be non-empty")

            elif stmt == "color_by_chain":
                if not args.get("sel", "").strip():
                    errors.append("color_by_chain.sel must be non-empty")
                tgt = args.get("target", "").strip().lower()
                if tgt not in allowed_rep_targets:
                    errors.append(
                        f"color_by_chain.target must be one of {sorted(allowed_rep_targets)}, got {args.get('target')!r}"
                    )

            elif stmt in ("color", "color_selection"):
                if not args.get("sel", "").strip():
                    errors.append(f"{stmt}.sel must be non-empty")
                rep = args.get("rep", "").strip().lower()
                if not rep:
                    errors.append(f"{stmt}.rep must be non-empty")
                elif rep not in allowed_rep_targets:
                    errors.append(
                        f"{stmt}.rep must be one of {sorted(allowed_rep_targets)}, got {args.get('rep')!r}"
                    )
                if not args.get("color", "").strip():
                    errors.append(f"{stmt}.color must be non-empty")

        if errors:
            return False, None, errors
        return True, ast, []
    except Exception as e:
        return False, None, [str(e)]

