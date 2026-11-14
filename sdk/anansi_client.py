"""Reference SDK (Python). Same contract the Unity/Unreal plugins will follow (DESIGN.md section 6):
try the gateway, fall back locally on timeout, 429 or 5xx, so the game always answers."""
import json

import httpx


class Anansi:
    def __init__(self, base_url, title, key, ticket, fallback=None, timeout=3.0, transport=None, gen_timeout=60.0):
        self.http = httpx.Client(transport=transport)
        self.base, self.gen_timeout = base_url.rstrip("/"), gen_timeout
        self.url, self.timeout = self.base + "/v1/chat/completions", timeout
        self.headers = {"X-Anansi-Title": title, "X-Anansi-Key": key, "X-Player-Token": ticket}
        # fallback(messages) -> str. Point it at a local llama-server in a real game; default is a canned line.
        self.fallback = fallback or (lambda messages: "...")

    def chat(self, messages, npc_id=None, structured=False, **params):
        body = {"messages": messages, "anansi": {"npc_id": npc_id, "structured": structured}, **params}
        try:
            r = self.http.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                d = r.json()
                text = d["choices"][0]["message"]["content"]
                out = {"source": "gateway", "filtered": d["anansi"]["filtered"], "action": "none"}  # same keys as the fallback
                if structured:
                    out.update(json.loads(text))
                else:
                    out["say"] = text
                return out
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"source": "fallback", "say": self.fallback(messages), "action": "none", "filtered": False}

    def chat_stream(self, messages, npc_id=None, **params):
        """Yield the reply one sentence at a time. If the gateway fails before the first sentence, yield the local
        fallback line instead; if it fails after, the sentences already shown stand (nothing is replayed).
        Plain replies only: structured actions use chat()."""
        body = {"messages": messages, "stream": True, "anansi": {"npc_id": npc_id}, **params}
        got = False
        try:
            with self.http.stream("POST", self.url, json=body, headers=self.headers, timeout=self.timeout) as r:
                if r.status_code == 200:
                    for line in r.iter_lines():
                        if not line.startswith("data: {"):
                            continue
                        d = json.loads(line[6:])
                        if "error" in d:
                            break
                        text = (d.get("choices") or [{}])[0].get("delta", {}).get("content")
                        if text:
                            got = True
                            yield text
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        if not got:
            yield self.fallback(messages)

    def quest(self, world, steps=3, theme="", difficulty="normal", story_so_far="", player="", fallback=None):
        """One quest built only from `world` (dict of npcs, locations, items, each a list of {id, name, role}).
        Returns {"source": "gateway" | "fallback", "quest": {...} or None}. On any failure `fallback(world)` supplies
        an authored quest if given; without one, quest is None so the game can use its own."""
        return self._generate("quest", fallback, world=world, steps=steps, theme=theme, difficulty=difficulty,
                              story_so_far=story_so_far, player=player)

    def storyline(self, world, beats=4, theme="", fallback=None):
        """A story arc: {"source", "storyline": {"logline", "beats": [{title, summary, npc_id, location_id}]} or None}."""
        return self._generate("storyline", fallback, world=world, steps=beats, theme=theme)

    def credits(self):
        """Volunteer credits of this player: {"balance", "pending", "nodes"}, or None when the gateway cannot be reached."""
        try:
            r = self.http.get(self.base + "/v1/credits", headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                d = r.json()
                return {k: d[k] for k in ("balance", "pending", "nodes")}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return None

    def link_node(self, code):
        """Link the machine that printed `code` (the node agent's --link) to this player. {"linked": True, balance, pending,
        nodes}, or {"linked": False, "reason": "bad_code" (unknown, used or expired) | "unavailable"}. Spending is not here:
        only the game's server may spend, with the title's server key."""
        try:
            r = self.http.post(self.base + "/v1/credits/link", json={"code": str(code)}, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                d = r.json()
                return {"linked": True, **{k: d[k] for k in ("balance", "pending", "nodes")}}
            if r.status_code in (400, 404):
                return {"linked": False, "reason": "bad_code"}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"linked": False, "reason": "unavailable"}

    def leaderboard(self, period="week", limit=25):
        """The public volunteer leaderboard: {"period", "nodes": [...], "users": [...]}, ranked by tokens processed in `period` ("day", "week"
        or "all"), or None when the gateway cannot be reached. Names and hardware text come from outside machines and players: escape them
        if you show them in markup."""
        try:
            r = self.http.get(self.base + "/v1/leaderboard", params={"period": period, "limit": limit}, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def set_leaderboard_name(self, name):
        """Opt this player in to the leaderboard under `name` (an empty name opts out). Shown once a machine is linked. {"set": True,
        "name": the cleaned name or None}, or {"set": False, "reason": "bad_name" (the name is refused: "message" says why, for example no links
        or email addresses) | "not_allowed" (the studio has switched names off, or blocked this account) | "unavailable"}."""
        try:
            r = self.http.post(self.base + "/v1/credits/name", json={"name": name}, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                return {"set": True, "name": r.json().get("name")}
            if r.status_code in (400, 403, 422):
                detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
                return {"set": False, "reason": "not_allowed" if r.status_code == 403 else "bad_name", "message": detail if isinstance(detail, str) else ""}
        except (httpx.HTTPError, ValueError):
            pass
        return {"set": False, "reason": "unavailable"}

    def _generate(self, kind, fallback, **body):
        try:  # generation is slow (tens of seconds on a small GPU), so it has its own, longer timeout
            r = self.http.post(self.base + "/v1/" + kind, json=body, headers=self.headers, timeout=self.gen_timeout)
            if r.status_code == 200:
                return {"source": "gateway", kind: r.json()[kind]}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"source": "fallback", kind: fallback(body["world"]) if fallback else None}
