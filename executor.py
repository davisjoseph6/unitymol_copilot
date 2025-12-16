import re
from pathlib import Path


def _esc(s: str) -> str:
    """Escape for inclusion inside double-quoted UnityMol command strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _norm_path(p: str) -> str:
    """Unity/Mono on Windows is fine with forward slashes; normalize for safety."""
    return p.replace("\\", "/")


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
                cmds.append(f'fetch("{_esc(pdbid)}")')

                # Ensure a stable "all" selection exists
                cmds.append('select("all", "all", True, False, True)')

                # Create all_<pdbid> selection name for downstream commands
                sel = f"all_{pdbid}"
                cmds.append(f'select("all", "{_esc(sel)}", True, False, True)')

            elif "filePath" in a:
                path = _norm_path(a["filePath"])
                cmds.append(f'load("{_esc(path)}")')

                # Ensure a stable "all" selection exists
                cmds.append('select("all", "all", True, False, True)')

                # If file stem looks like a PDB id, create all_<stem>
                stem = Path(path).stem.lower()
                if re.fullmatch(r"[0-9][a-z0-9]{3}", stem):
                    sel = f"all_{stem}"
                    cmds.append(f'select("all", "{_esc(sel)}", True, False, True)')

            else:
                raise ValueError("add_structure requires PDBID or filePath")

        elif s == "select":
            query = _esc(a["query"])
            name = _esc(a.get("name", "selection"))
            # select(string selMDA, string name="selection", bool createSelection=True,
            #        bool addToExisting=False, bool forceCreate=True)
            cmds.append(f'select("{query}", "{name}", True, False, True)')

        elif s == "show":
            sel = _esc(a["sel"])
            rep = _esc(a["rep"])
            cmds.append(f'showSelection("{sel}", "{rep}")')

        elif s == "hide":
            sel = _esc(a["sel"])
            cmds.append(f'hideSelection("{sel}")')

        elif s == "color_by_chain":
            sel = _esc(a["sel"])
            target = _esc(a["target"].lower())
            # UnityMol: colorByChain(string selName, string type)
            cmds.append(f'colorByChain("{sel}", "{target}")')

        else:
            raise NotImplementedError(s)

    return cmds

