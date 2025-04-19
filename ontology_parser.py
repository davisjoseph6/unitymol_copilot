# unitymol_command_parser.py

# Simple parser with ontology-driven reasoning and command mapping
import json
import re

# --- Ontology: Basic RDF-style triples (subject, predicate, object) ---
ONTOLOGY = [
    ("protein", "is_a", "molecule"),
    ("ligand", "is_a", "molecule"),
    ("water", "is_a", "solvent"),
    ("solvent", "is_a", "molecule"),
    ("blue", "is_a", "color"),
    ("red", "is_a", "color"),
    ("green", "is_a", "color"),
    ("hide", "is_a", "action"),
    ("show", "is_a", "action"),
    ("color", "is_a", "action"),
    ("center", "is_a", "action"),
    ("paint", "same_as", "color"),
    ("highlight", "same_as", "color"),
    ("focus", "same_as", "center"),
]

# Simple reasoning helpers
def resolve_term(term):
    for s, p, o in ONTOLOGY:
        if s == term and p == "same_as":
            return o
    return term

def normalize_subject(term):
    term = term.strip().lower()
    term = re.sub(r"^(the|a|an) ", "", term)
    return resolve_term(term)

def get_class(term):
    for s, p, o in ONTOLOGY:
        if s == term and p == "is_a":
            return o
    return None

# --- Main parser ---
def parse_command(cmd_json):
    if isinstance(cmd_json, dict):
        action = cmd_json.get("action")
        target = cmd_json.get("target")
        color = cmd_json.get("color")

        if action == "color" and target and color:
            return f'cmds.colorSelection("{color}", selection="{target}")'

        elif action == "center" and target:
            return f'cmds.center(selection="{target}")'

        elif action == "hide" and target:
            return f'cmds.setVisibility(selection="{target}", visible=False)'

        elif action == "show" and target:
            return f'cmds.setVisibility(selection="{target}", visible=True)'

    return f"# Unrecognized structured command: {cmd_json}"

# --- Natural Language to Structured JSON Command ---
def nl_to_structured_command(nl):
    nl = nl.lower()
    for synonym, _, canonical in ONTOLOGY:
        if synonym in nl:
            nl = nl.replace(synonym, canonical)

    # Match color commands
    match = re.search(r'(color|paint|highlight) (.+?) in (\w+)', nl)
    if match:
        action = resolve_term(match.group(1))
        target = normalize_subject(match.group(2))
        color = match.group(3).strip()
        return {"action": action, "target": target, "color": color}

    # Match center/focus commands
    match = re.search(r'(center|focus) on (.+)', nl)
    if match:
        action = resolve_term(match.group(1))
        target = normalize_subject(match.group(2))
        return {"action": action, "target": target}

    # Match hide/show commands
    match = re.search(r'(hide|show) (.+)', nl)
    if match:
        action = resolve_term(match.group(1))
        target = normalize_subject(match.group(2))
        return {"action": action, "target": target}

    return {"error": "Could not parse input"}

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
        print(f"→ Structured JSON: {json.dumps(structured)}")
        print(f"→ IronPython: {parse_command(structured)}")
        print("-")

