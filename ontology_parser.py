import json

# Simple ontology for mapping terms to categories and canonical UnityMol targets
ONTOLOGY = {
    "protein": {"type": "molecule", "canonical": "protein"},
    "ligand": {"type": "molecule", "canonical": "ligand"},
    "solvent": {"type": "molecule", "canonical": "solvent"},
    "water": {"type": "molecule", "canonical": "water"}
}

# Simple action mapping
ACTIONS = {
    "color": "color",
    "paint": "color",
    "highlight": "color",
    "center": "center",
    "focus": "center",
    "hide": "hide",
    "show": "show"
}

def parse_input(text):
    words = text.lower().split()
    action = None
    color = None
    target = None

    # Identify the action
    for word in words:
        if word in ACTIONS:
            action = ACTIONS[word]
            break

    # Identify color (simple heuristic: check against known color names)
    known_colors = ["red", "blue", "green", "yellow", "orange", "purple", "white", "black"]
    for word in words:
        if word in known_colors:
            color = word
            break

    # Identify target based on ontology
    for word in words:
        if word in ONTOLOGY:
            target = ONTOLOGY[word]["canonical"]
            break

    # Validation
    if not action:
        return {"error": "No recognized action in input"}
    if not target:
        return {"error": "No recognized target in input"}
    
    result = {"action": action, "target": target}
    if color:
        result["color"] = color
    return result

def to_ironpython(parsed):
    if "error" in parsed:
        return f"# Unrecognized structured command: {parsed}"

    action = parsed["action"]
    target = parsed["target"]

    if action == "color" and "color" in parsed:
        return f'cmds.colorSelection("{parsed["color"]}", selection="{target}")'
    elif action == "center":
        return f'cmds.center(selection="{target}")'
    elif action == "hide":
        return f'cmds.hide(selection="{target}")'
    elif action == "show":
        return f'cmds.show(selection="{target}")'
    else:
        return f"# Unsupported structured command: {parsed}"

if __name__ == '__main__':
    while True:
        try:
            line = input("Input: ").strip()
            if not line:
                break
            structured = parse_input(line)
            print("→ Structured JSON:", json.dumps(structured))
            print("→ IronPython:", to_ironpython(structured))
            print("-")
        except (EOFError, KeyboardInterrupt):
            break

