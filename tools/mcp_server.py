"""MCP server for game developers: lets an AI coding assistant (Claude Code, Cursor, ...) try Anansi while you build.

    pip install -r requirements-mcp.txt
    ANANSI_URL=http://127.0.0.1:8080 ANANSI_TITLE=demo ANANSI_KEY=change-me python tools/mcp_server.py

Tools: npc_say (talk to an NPC through the gateway), generate_quest, generate_storyline, check_config (lint a gateway
config file without starting it). It is a development aid: point it at a staging gateway with a test title key. It
holds no admin token, never changes a config and never bans anything. The game itself keeps using the SDKs.
Add to Claude Code:  claude mcp add anansi -e ANANSI_URL=... -e ANANSI_KEY=... -- python tools/mcp_server.py
shortcut: one title per server process (the env vars); run several servers for several titles. No red-team tool yet."""
import json
import os
import sys

import httpx

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from gateway.app import make_app  # noqa: E402

TRANSPORT = None  # tests put an in-process app here


async def _post(path, body):
    headers = {"X-Anansi-Title": os.environ.get("ANANSI_TITLE", "demo"), "X-Anansi-Key": os.environ.get("ANANSI_KEY", ""),
               "X-Player-Token": os.environ.get("ANANSI_PLAYER", "dev:mcp-tester")}
    async with httpx.AsyncClient(base_url=os.environ.get("ANANSI_URL", "http://127.0.0.1:8080"), timeout=180,
                                 transport=TRANSPORT) as c:
        try:
            r = await c.post(path, json=body, headers=headers)
        except httpx.HTTPError as e:
            return {"error": f"gateway unreachable: {e.__class__.__name__}"}
    try:
        data = r.json()
    except ValueError:
        data = {"detail": r.text[:200]}
    if r.status_code != 200:  # hand the status to the assistant instead of raising: 429 and 503 mean something
        return {"error": r.status_code, **(data if isinstance(data, dict) else {"detail": data})}
    return data


async def npc_say(message: str, npc_id: str = "", structured: bool = False, persona: str = "") -> dict:
    """Say one line to an NPC as a player and return what the player would receive: say, action, filtered, node.
    npc_id keeps the same NPC on the same node. structured=True also returns one of the title's allowed actions.
    persona is an optional extra system message to try wording on top of the title's own prompt; the title's real
    prompt lives in the gateway config. filtered=True means the safety checks blocked the model's reply and the
    player would see the fallback line instead."""
    msgs = ([{"role": "system", "content": persona}] if persona else []) + [{"role": "user", "content": message}]
    return await _post("/v1/npc", {"messages": msgs, "npc_id": npc_id or None, "structured": structured})


async def generate_quest(world: dict, theme: str = "", steps: int = 3, difficulty: str = "normal") -> dict:
    """Generate one quest from your own world data. world = {"npcs": [{"id","name","role"}], "locations": [...],
    "items": [...]}; every id in the answer is one of yours. Returns {"quest": {...}} or {"error": status}."""
    return await _post("/v1/quest", {"world": world, "theme": theme, "steps": steps, "difficulty": difficulty})


async def generate_storyline(world: dict, theme: str = "", steps: int = 3, story_so_far: str = "") -> dict:
    """Generate a short story arc from your own world data (same world shape as generate_quest)."""
    return await _post("/v1/storyline", {"world": world, "theme": theme, "steps": steps, "story_so_far": story_so_far})


def check_config(path: str) -> dict:
    """Lint a gateway config file: the same startup checks the gateway runs (so a problem that would stop it from
    starting shows up here), plus warnings about weak title settings. Starts nothing and touches no database."""
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "issues": [{"level": "error", "where": path, "message": f"cannot read config: {e}"}]}
    issues = []

    def add(level, where, message):
        issues.append({"level": level, "where": where, "message": message})
    try:
        make_app({**cfg, "db_path": None})
    except Exception as e:  # startup refusals are ValueError, but a missing key is a KeyError: report both
        add("error", "startup", f"{e.__class__.__name__}: {e}")
    if (cfg.get("auth") or cfg.get("steam") or {}).get("mode") == "dev":
        add("warn", "auth", "dev auth accepts any 'dev:<id>' token; the gateway refuses it when ANANSI_ENV=production")
    if not cfg.get("db_path"):
        add("warn", "db_path", "no database file: daily budgets and bans are lost on every restart")
    for name, t in (cfg.get("titles") or {}).items():
        if t.get("key") == "change-me":
            add("error", name, "title key is the example 'change-me'")
        if not t.get("fallback_line"):
            add("warn", name, "no fallback_line: a blocked reply has nothing to say instead")
        if not t.get("blocklist"):
            add("warn", name, "no blocklist")
        if t.get("judge") is None:
            add("warn", name, "no safety judge: only regex rules and the prompt-leak check stand between the model and the player")
        if t.get("actions") and not t.get("action_gates"):
            add("warn", name, "actions have no action_gates: the model could pick an action the player never asked for")
        if t.get("allow_overflow"):
            add("info", name, "allow_overflow: player text and the secret system prompt go to the paid API provider")
        if t.get("allow_volunteers"):
            add("warn", name, "allow_volunteers: volunteer machines see every prompt, including the secret system prompt")
        elif cfg.get("pull_tokens"):
            add("info", name, "volunteer nodes are configured but this title does not use them (allow_volunteers is off)")
    return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues}


def main():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("anansi")
    for fn in (npc_say, generate_quest, generate_storyline, check_config):
        server.tool()(fn)
    server.run()


if __name__ == "__main__":
    main()
