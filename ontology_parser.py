# unitymol_command_parser.py

# Simple parser with ontology-driven reasoning and command mapping
import json

# --- Ontology: Basic RDF-style triples (subject, predicate, object) ---
ONTOLOGY = [
    ("protein", "is_a", "molecule"),
    ("ligand", "is_a", "molecule"),
    ("water", "is_a", "solvent"),
    ("solvent", "is_a", "molecule"),
    ("blue", "is_a", "color"),
    ("hide", "is_a", "action"),
    ("show", "is_a", "action"),
    ("color", "is_a", "action"),
    ("center", "is_a", "action"),
    ("paint", "same_as", "color"),
    ("highlight", "same_as", "color"),
    ("focus", "same_as", "center"),
]

# Simple reasoning helper
def resolve_term(term):
    for s, p, o in ONTOLOGY:
        if s == term and p == "same_as":
            return o
    return term

# Get type/class of a subject
def get_class(term):
    for s, p, o in ONTOLOGY:
        if s == term and p == "is_a":
            return o
    return None

# --- Main parser ---
def parse_command(cmd):
    if isinstance(cmd, str):
        if cmd.startswith("setColor"):
            parts = cmd[9:-1].split(",")
            target = parts[0].strip().strip("\"'")
            color = parts[1].strip().strip("\"'")
            return f'cmds.colorSelection("{color}", selection="{target}")'

        elif cmd.startswith("centerOn"):
            target = cmd[9:-1].strip().strip("\"'")
            return f'cmds.center(selection="{target}")'

        elif cmd.startswith("hide"):
            target = cmd[5:-1].strip().strip("\"'")
            return f'cmds.setVisibility(selection="{target}", visible=False)'

        elif cmd.startswith("show"):
            target = cmd[5:-1].strip().strip("\"'")
            return f'cmds.setVisibility(selection="{target}", visible=True)'

    return f"# Unrecognized command: {cmd}"

# --- Natural Language to Structured Command (simplified) ---
def nl_to_structured_command(nl):
    nl = nl.lower()
    for synonym, _, canonical in ONTOLOGY:
        if synonym in nl:
            nl = nl.replace(synonym, canonical)

    if "color" in nl:
        parts = nl.split("color")[-1].strip().split(" in ")
        if len(parts) == 2:
            target = parts[0].strip()
            color = parts[1].strip()
            return f'setColor("{target}", "{color}")'

    elif "center on" in nl:
        target = nl.split("center on")[-1].strip()
        return f'centerOn("{target}")'

    elif "hide" in nl:
        target = nl.split("hide")[-1].strip()
        return f'hide("{target}")'

    elif "show" in nl:
        target = nl.split("show")[-1].strip()
        return f'show("{target}")'

    return "# Could not parse input"

# --- Test area ---
if __name__ == "__main__":
    tests = [
        "color the protein in blue",
        "paint the ligand in red",
        "focus on the water",
        "hide the solvent",
        "highlight the protein in green",
    ]

    for test in tests:
        structured = nl_to_structured_command(test)
        print(f"Input: {test}")
        print(f"→ Structured: {structured}")
        print(f"→ IronPython: {parse_command(structured)}")
        print("-")

