"""Reference SDK (Python). Same contract the Unity/Unreal plugins will follow (DESIGN.md section 6):
try the gateway, fall back locally on timeout, 429 or 5xx, so the game always answers."""
import json
import re
import time

import httpx

# Direct fallback (off unless set): when the gateway cannot be reached, ask a public LLM straight from the game. Default is
# Pollinations' keyless endpoint, which allows one reply per player IP every 45 s (measured 2026-11-15; it changes); the SDK spaces calls 60 s apart by default and keeps to
# that itself (their terms forbid evading limits). None of the gateway's checks run there, so the reply is checked here.
DIRECT_URL = "https://text.pollinations.ai/openai"
GATEWAY_GONE = (502, 503, 504)  # a proxy in front of a gateway that is down; 401, 403 and 429 are answers, not absence
AI_TALK = re.compile(r"\b(i am|i'm|as) (just |only )?an? (ai|a\.i\.|llm|chatbot|language model|artificial intelligence|(computer )?program|software|bot)\b"
                     r"|\blanguage model\b", re.I)
ACTION_LABEL = re.compile(r"\s*action\s*[:=]\s*\w+\W*$", re.I)
# the gateway's order rule (gateway/app.py ORDER): a player who commands or claims authority gets no action
ORDER = re.compile(r"\b(i demand|no haggling|do it now|you (must|have to|will)|i am your (manager|boss|developer|admin\w*)"
                   r"|system (notice|message)|the developer says|your instructions)\b", re.I)


def forced(line, actions):
    """True if the player's line tries to pick the action instead of earning it: it names an action, says "action", or gives
    an order. The gateway refuses any action then, and so does the direct fallback."""
    names = "|".join(re.escape(a) for a in actions)
    return bool(re.search(r"\b(" + names + r")\b|\baction\b", line or "", re.I) or ORDER.search(line or ""))


def check_direct(text, system, actions, structured, max_chars=600):
    """(say, action) from a direct reply, or None if it must not reach the player: no usable text, an AI or language-model
    statement, or five words in a row copied from the NPC's prompt. An action not in `actions` becomes "none"."""
    act = "none"
    if structured:
        m = re.search(r"\{.*\}", text or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else None
        except ValueError:
            d = None
        if not isinstance(d, dict):
            return None
        text, act = str(d.get("say", "")), d.get("action", "none")
        act = act if act in actions else "none"
    lines = (" ".join(line.split()) for line in ACTION_LABEL.sub("", text or "").split("\n"))  # line breaks kept: some prompts ask for lines
    say = "\n".join(line for line in lines if line)[:max_chars].strip()
    words = re.findall(r"\w+", system.lower())
    grams = {" ".join(words[i:i + 5]) for i in range(len(words) - 4)}
    said = re.findall(r"\w+", say.lower())
    if not say or AI_TALK.search(say) or any(" ".join(said[i:i + 5]) in grams for i in range(len(said) - 4)):
        return None
    return say, act


class Anansi:
    _next_direct = 0.0  # shared by every client in the process: the free limit is per player IP, not per client

    def __init__(self, base_url, title, key, ticket, fallback=None, timeout=3.0, transport=None, gen_timeout=60.0, direct=None):
        """direct (optional): {"system": the NPC's prompt, "actions": [...], "url", "model", "min_interval_s", "timeout_s"}.
        When the gateway cannot be reached, chat() asks that LLM directly (default: Pollinations, keyless) before the local
        fallback. The prompt ships in your game, the player's text goes to that service, and only the checks in
        check_direct() apply: see docs/sdk.md before turning it on."""
        self.http = httpx.Client(transport=transport)
        self.direct = direct
        self.base, self.gen_timeout = base_url.rstrip("/"), gen_timeout
        self.url, self.timeout = self.base + "/v1/chat/completions", timeout
        self.headers = {"X-Anansi-Title": title, "X-Anansi-Key": key, "X-Player-Token": ticket}
        # fallback(messages) -> str. Point it at a local llama-server in a real game; default is a canned line.
        self.fallback = fallback or (lambda messages: "...")

    def chat(self, messages, npc_id=None, structured=False, **params):
        body = {"messages": messages, "anansi": {"npc_id": npc_id, "structured": structured}, **params}
        gone = False
        try:
            r = self.http.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
            gone = r.status_code in GATEWAY_GONE
            if r.status_code == 200:
                d = r.json()
                text = d["choices"][0]["message"]["content"]
                out = {"source": "gateway", "filtered": d["anansi"]["filtered"], "action": "none"}  # same keys as the fallback
                if structured:
                    out.update(json.loads(text))
                else:
                    out["say"] = text
                return out
        except (httpx.ConnectError, httpx.ConnectTimeout):  # no connection at all: the gateway is not there
            gone = True
        except (httpx.HTTPError, ValueError, KeyError):  # slow (a read timeout) or a broken reply: the gateway is there and
            pass                                          # may still answer and bill, so the local line, not a third party
        d = self._direct(messages, structured) if gone else None
        if d:
            return {"source": "direct", "say": d[0], "action": d[1], "filtered": False}
        return {"source": "fallback", "say": self.fallback(messages), "action": "none", "filtered": False}

    def _direct(self, messages, structured):
        """(say, action) from the direct LLM, or None (off, too soon after the last call, no answer, or failed the checks)."""
        c, cls = self.direct, type(self)
        if not c or time.monotonic() < cls._next_direct:
            return None
        cls._next_direct = time.monotonic() + c.get("min_interval_s", 60)
        actions = list(c.get("actions") or [])
        own = "\n".join(m["content"] for m in messages if m.get("role") == "system")  # the game's NPC persona
        prompt = c["system"] + ("\n" + own if own else "")
        system = prompt + ("" if not structured else " Reply with only a JSON object, no other text, shaped like this: "
                                '{"say": "<what you say>", "action": ' + " | ".join(json.dumps(a) for a in actions + ["none"]) + "}")
        started, limit = time.monotonic(), c.get("timeout_s", 20)
        send = lambda: self.http.post(c.get("url", DIRECT_URL), timeout=max(1.0, limit - (time.monotonic() - started)), json={
            "model": c.get("model", "openai"), "max_tokens": c.get("max_tokens", 400),
            "messages": [{"role": "system", "content": system}] + [m for m in messages if m.get("role") in ("user", "assistant")][-8:]})
        try:
            r = send()
            wait = float(r.headers.get("Retry-After", 60)) if r.status_code == 402 else 0
            if wait and wait <= c.get("retry_within_s", 15) and time.monotonic() - started + wait < limit:
                time.sleep(wait + 0.25)  # another app on this address had the slot: wait as told, once
                r = send()
            if r.status_code == 402:  # over the free limit: wait as long as it says
                cls._next_direct = time.monotonic() + float(r.headers.get("Retry-After", 60))
            if r.status_code != 200:
                return None
            ok = check_direct(r.json()["choices"][0]["message"]["content"], prompt, actions, structured, c.get("max_chars", 600))
            last = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
            return (ok[0], "none") if ok and ok[1] != "none" and forced(last, actions) else ok
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return None

    def chat_stream(self, messages, npc_id=None, **params):
        """Yield the reply one sentence at a time. If the gateway fails before the first sentence, yield the local
        fallback line instead; if it fails after, the sentences already shown stand (nothing is replayed).
        Plain replies only: structured actions use chat()."""
        body = {"messages": messages, "stream": True, "anansi": {"npc_id": npc_id}, **params}
        got = gone = False
        try:
            with self.http.stream("POST", self.url, json=body, headers=self.headers, timeout=self.timeout) as r:
                gone = r.status_code in GATEWAY_GONE
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
        except (httpx.ConnectError, httpx.ConnectTimeout):  # no connection at all: the gateway is not there
            gone = True
        except (httpx.HTTPError, ValueError, KeyError):  # slow or broken, but there: no direct call
            pass
        if not got:  # shortcut: a stream that never started tries the direct LLM whole, not sentence by sentence
            d = self._direct(messages, False) if gone else None  # never after a refusal (401, 403, 429)
            yield d[0] if d else self.fallback(messages)

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

    def leaderboard(self, period="week", limit=20):
        """The anonymous volunteer-network statistics for `period` ("day", "week" or "all"), or None when the gateway cannot be reached:
        {"published", "min_group", "reporting": {"machines", "tokens", "idle_gpu_pct"}, "network_tokens", "gpus": [...], "cpus": [...],
        "systems": [...]} where each row is {"name", "machines", "tokens", "idle_gpu_pct"}. Nothing is published (published is False and the
        rest empty) until at least min_group machines report, and a group smaller than that is folded into "Other". The names are hardware
        names reported by machines: escape them if you show them in markup."""
        try:
            r = self.http.get(self.base + "/v1/leaderboard", params={"period": period, "limit": limit}, timeout=self.timeout)
            if r.status_code == 200:
                return r.json()
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def _generate(self, kind, fallback, **body):
        try:  # generation is slow (tens of seconds on a small GPU), so it has its own, longer timeout
            r = self.http.post(self.base + "/v1/" + kind, json=body, headers=self.headers, timeout=self.gen_timeout)
            if r.status_code == 200:
                return {"source": "gateway", kind: r.json()[kind]}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        return {"source": "fallback", kind: fallback(body["world"]) if fallback else None}
