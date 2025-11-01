import re
from lark import Lark, Transformer

GRAMMAR = r"""
?start: (stmt NEWLINE?)+

?stmt: add_structure
     | select_stmt
     | show_stmt
     | hide_stmt
     | color_by_chain_stmt

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

%import common.ESCAPED_STRING
%import common.WS
%import common.NEWLINE
%ignore WS
"""

_parser = Lark(GRAMMAR, start="start", maybe_placeholders=False)

def _unq(tok):
    # tok is an ESCAPED_STRING like '"abc"'
    s = str(tok)
    return s[1:-1]

class BuildAST(Transformer):
    # --- add_structure ---
    def arg_pdbid(self, items):
        return ("PDBID", _unq(items[0]))

    def arg_file(self, items):
        return ("filePath", _unq(items[0]))

    def add_args(self, items):
        # items are tuples returned by arg_pdbid/arg_file
        return {k: v for (k, v) in items}

    def add_structure(self, items):
        args = items[0] if items else {}
        return {"stmt": "add_structure", "args": args}

    # --- select ---
    def select_stmt(self, items):
        # items: [query_str, (optional) name_str]
        query = _unq(items[0])
        name = _unq(items[1]) if len(items) > 1 else "selection"
        return {"stmt": "select", "args": {"query": query, "name": name}}

    # --- show/hide ---
    def show_stmt(self, items):
        sel = _unq(items[0])
        rep = _unq(items[1])
        return {"stmt": "show", "args": {"sel": sel, "rep": rep}}

    def hide_stmt(self, items):
        sel = _unq(items[0])
        return {"stmt": "hide", "args": {"sel": sel}}

    # --- color_by_chain ---
    def color_by_chain_stmt(self, items):
        sel = _unq(items[0])
        target = _unq(items[1])
        return {"stmt": "color_by_chain", "args": {"sel": sel, "target": target}}

def parse_and_validate_molcommand(program: str):
    """
    Parse a molcommand script and return (ok: bool, ast: list[dict] | None, errors: list[str]).
    """
    try:
        text = program if program.endswith("\n") else program + "\n"
        tree = _parser.parse(text)

        ast = []
        tr = BuildAST()
        for node in tree.children:
            ast.append(tr.transform(node))

        # ---- semantic checks ----
        errors = []
        allowed_target_kinds = {"atom", "bond", "cartoon", "surface", "point", "tube", "line"}

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
                if has_file:
                    if not args["filePath"]:
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
                if not args.get("rep", "").strip():
                    errors.append("show.rep must be non-empty")
                # (Optional) you may restrict rep vocabulary here if desired.

            elif stmt == "hide":
                if not args.get("sel", "").strip():
                    errors.append("hide.sel must be non-empty")

            elif stmt == "color_by_chain":
                if not args.get("sel", "").strip():
                    errors.append("color_by_chain.sel must be non-empty")
                tgt = args.get("target", "").strip().lower()
                if tgt not in allowed_target_kinds:
                    errors.append(
                        f"color_by_chain.target must be one of {sorted(allowed_target_kinds)}, got {args.get('target')!r}"
                    )

        if errors:
            return False, None, errors
        return True, ast, []
    except Exception as e:
        return False, None, [str(e)]

