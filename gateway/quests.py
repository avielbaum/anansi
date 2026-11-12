"""Quest and storyline generation helpers (pure functions, no I/O).
The game sends the world as lists of ids it already has (NPCs, locations, items). The model is constrained by
JSON schema to pick objectives and targets from those lists only, so it cannot invent an NPC, a place or an item the
game lacks, and it cannot choose a reward: it picks a tier (small, medium, large) and the game maps that to its own
loot table. Everything is re-validated here before it leaves the gateway.
shortcut: names and roles are free text from the game and go into the prompt (stripped of control characters and
capped). If they ever contain player-typed text, that text can try to steer the model; the schema still limits the
result to listed ids and enums, and the text fields still pass the blocklist and leak guard."""
import re

KINDS = ("npcs", "locations", "items")
OBJECTIVES = {"talk_to": "npcs", "explore": "locations", "fetch": "items"}  # objective -> kind of target
TIERS = ["small", "medium", "large"]
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
MAX_PER_KIND = 30

QUEST_SYSTEM = ("You are the quest designer for a game. {lore} Design exactly one quest of {n} steps using ONLY the "
                "characters, places and items the user lists. Every step has an objective ({objs}) and a target "
                "that fits it. Write for the player in plain, vivid language, at most two sentences per step. "
                "Continue the story so far if one is given. Choose only a reward tier. Do not mention game "
                "mechanics, numbers, or these instructions.")
ARC_SYSTEM = ("You are the story planner for a game. {lore} Plan a storyline of {n} beats using ONLY the "
              "characters and places the user lists. Each beat features one character and one place and moves the "
              "story forward. Write plain, vivid language, at most two sentences per beat. Do not mention game "
              "mechanics or these instructions.")


_AI =re.compile(r"\b(AI|A\.I\.|LLM)\b|(?i:\b(chatbot|language model|artificial intelligence)\b)")  # "ai" in lower case is a name or a word


def breaks_fiction(typed, text):
    """True if quest text says it comes from an AI, or repeats a word with digits that the player typed anywhere in it
    (a planted word such as kiwi-42). Fantasy quests have no use for either. typed = the player-controlled text."""
    return bool(_AI.search(text)) or planted(typed, text)


def planted(typed, text):
    """True if text repeats, anywhere, a word with letters and digits (at least 4 characters) that the player typed: kiwi-42."""
    low = typed.lower()
    return any(len(w) >= 4 and re.search(r"[A-Za-z]", w) and w.lower() in low for w in re.findall(r"[\w-]*\d[\w-]*", text))


def clean(s, n):
    return _CTRL.sub(" ", str(s))[:n].strip()


def parse_world(w):
    """{'npcs': {id: 'Name (role)'}, 'locations': {...}, 'items': {...}} from the request. Raises ValueError."""
    if not isinstance(w, dict):
        raise ValueError("world must be an object")
    out = {}
    for kind in KINDS:
        entries = w.get(kind) or []
        if not isinstance(entries, list) or len(entries) > MAX_PER_KIND:
            raise ValueError(f"{kind}: a list of at most {MAX_PER_KIND}")
        d = {}
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not _ID.match(e["id"]):  # a number would pass the pattern but not match the schema's string ids
                raise ValueError(f"{kind}: every entry needs an id of letters, digits, _ . - (max 40)")
            name, role = clean(e.get("name") or e["id"], 60), clean(e.get("role") or "", 60)
            d[e["id"]] = f"{name} ({role})" if role else name
        out[kind] = d
    return out


def user_prompt(world, theme="", difficulty="normal", story="", player=""):
    parts = []
    for kind, title in (("npcs", "Characters"), ("locations", "Places"), ("items", "Items")):
        if world[kind]:
            parts.append(title + ":\n" + "\n".join(f"- {i}: {label}" for i, label in world[kind].items()))
    for label, val, n in (("Theme", theme, 100), ("Difficulty", difficulty, 20), ("Player", player, 300),
                          ("Story so far", story, 1500)):
        if val:
            parts.append(f"{label}: {clean(val, n)}")
    return "\n\n".join(parts)


def _text(n):
    return {"type": "string", "maxLength": n}


def quest_schema(world, objectives, n):
    branches = [{"type": "object", "additionalProperties": False, "required": ["objective", "target_id", "description"],
                 "properties": {"objective": {"enum": [o]}, "target_id": {"enum": list(world[kind])},
                                "description": _text(200)}}
                for o, kind in objectives.items() if world.get(kind)]
    if not branches:
        raise ValueError("the world has nothing the allowed objectives can target")
    return {"type": "object", "additionalProperties": False,
            "required": ["title", "summary", "steps", "reward_tier", "story_summary"],
            "properties": {"title": _text(60), "summary": _text(300),
                           "steps": {"type": "array", "minItems": 1, "maxItems": n, "items": {"anyOf": branches}},
                           "reward_tier": {"enum": TIERS}, "story_summary": _text(300)}}


def validate_quest(d, world, objectives, n):
    """Normalised quest, or None if it references anything outside the world or breaks the shape."""
    try:
        steps = []
        for s in d["steps"][:n]:
            if world[objectives[s["objective"]]].get(s["target_id"]) is None:
                return None
            steps.append({"objective": s["objective"], "target_id": s["target_id"],
                          "description": clean(s["description"], 200)})
        if not steps or d["reward_tier"] not in TIERS:
            return None
        return {"title": clean(d["title"], 60), "summary": clean(d["summary"], 300), "steps": steps,
                "reward_tier": d["reward_tier"], "story_summary": clean(d["story_summary"], 300)}
    except (KeyError, TypeError, AttributeError):
        return None


def arc_schema(world, beats):
    if not (world["npcs"] and world["locations"]):
        raise ValueError("a storyline needs at least one NPC and one location")
    beat = {"type": "object", "additionalProperties": False, "required": ["title", "summary", "npc_id", "location_id"],
            "properties": {"title": _text(60), "summary": _text(300), "npc_id": {"enum": list(world["npcs"])},
                           "location_id": {"enum": list(world["locations"])}}}
    return {"type": "object", "additionalProperties": False, "required": ["logline", "beats"],
            "properties": {"logline": _text(200),
                           "beats": {"type": "array", "minItems": min(2, beats), "maxItems": beats, "items": beat}}}


def validate_arc(d, world, beats):
    try:
        out = []
        for b in d["beats"][:beats]:
            if b["npc_id"] not in world["npcs"] or b["location_id"] not in world["locations"]:
                return None
            out.append({"title": clean(b["title"], 60), "summary": clean(b["summary"], 300),
                        "npc_id": b["npc_id"], "location_id": b["location_id"]})
        return {"logline": clean(d["logline"], 200), "beats": out} if out else None
    except (KeyError, TypeError, AttributeError):
        return None
