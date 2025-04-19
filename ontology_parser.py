import rdflib
import re
import json

# Load ontology
graph = rdflib.Graph()
graph.parse("ontology.ttl", format="turtle")

# Map synonyms to canonical entities from ontology
synonyms = {
    "protein": "protein",
    "ligand": "ligand",
    "substrate": "ligand",
    "water": "water",
    "solvent": "solvent"
}

action_map = {
    "color": ["color", "paint", "highlight"],
    "center": ["focus", "center"],
    "hide": ["hide"]
}

# Invert action map for lookup
action_lookup = {v: k for k, lst in action_map.items() for v in lst}

def is_valid_target(entity):
    q = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    ASK {{
        ?s rdfs:label "{entity}"@en .
    }}
    """
    return bool(graph.query(q))

def parse_command(input_text):
    input_text = input_text.strip().lower()

    # Match basic pattern: action + object + optional color
    color_match = re.match(r"(\\w+) the (\\w+) in (\\w+)", input_text)
    focus_match = re.match(r"(focus|center) on the (\\w+)", input_text)
    hide_match = re.match(r"hide the (\\w+)", input_text)

    if color_match:
        verb, obj, color = color_match.groups()
        action = action_lookup.get(verb)
        target = synonyms.get(obj, obj)
        if action and is_valid_target(target):
            return json.dumps({"action": action, "target": obj, "color": color})
    elif focus_match:
        _, obj = focus_match.groups()
        action = "center"
        target = synonyms.get(obj, obj)
        if is_valid_target(target):
            return json.dumps({"action": action, "target": obj})
    elif hide_match:
        obj = hide_match.group(1)
        action = "hide"
        target = synonyms.get(obj, obj)
        if is_valid_target(target):
            return json.dumps({"action": action, "target": obj})

    return json.dumps({"error": "Could not parse input"})

def to_ironpython(parsed_json):
    try:
        cmd = json.loads(parsed_json)
        if "error" in cmd:
            return f"# Unrecognized structured command: {cmd}"
        action = cmd["action"]
        target = cmd["target"]
        if action == "color":
            return f'cmds.colorSelection("{cmd["color"]}", selection="{target}")'
        elif action == "center":
            return f'cmds.center(selection="{target}")'
        elif action == "hide":
            return f'cmds.setVisibility("{target}", visible=False)'
    except Exception as e:
        return f"# Error interpreting structured command: {e}"

    return "# Could not convert structured command"

# Tests
examples = [
    "color the protein in blue",
    "paint the ligand in red",
    "focus on the water",
    "hide the solvent",
    "highlight the protein in green"
]

for ex in examples:
    structured = parse_command(ex)
    iron = to_ironpython(structured)
    print("Input:", ex)
    print("→ Structured JSON:", structured)
    print("→ IronPython:", iron)
    print("-")

