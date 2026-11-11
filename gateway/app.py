"""Anansi gateway, Phase 1 MVP (DESIGN.md sections 1, 6, 11, 12).
OpenAI-compatible POST /v1/chat/completions in front of any OpenAI-compatible nodes
(vLLM, llama-server, the mock in tools/). Non-streaming only: the output filter needs the whole reply."""
import datetime
import hmac
import json
import os
import re
import time

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .scheduler import Scheduler

STEAM_URL = "https://partner.steam-api.com/ISteamUserAuth/AuthenticateUserTicket/v1/"
FORWARD = ("model", "messages", "temperature", "top_p")  # everything else is dropped on purpose
MAX_BODY = 64_000


def make_app(config=None, transport=None):
    cfg = config or json.load(open(os.environ["ANANSI_CONFIG"], encoding="utf-8"))
    sched = Scheduler(cfg["nodes"])
    client = httpx.AsyncClient(transport=transport, timeout=cfg.get("upstream_timeout_s", 20))
    ticket_cache = {}  # shortcut: per-process caches, move to Redis when running more than one gateway
    usage = {}
    app = FastAPI()
    app.state.sched = sched

    def title_of(tid, key):
        t = cfg["titles"].get(tid or "")
        if not t or not hmac.compare_digest(t["key"].encode(), (key or "").encode()):
            raise HTTPException(401, "bad title credentials")
        return t

    async def steam_id(t, ticket):
        if cfg["steam"]["mode"] == "dev":  # dev tickets look like "dev:<steamid>"; never use in production
            if ticket and ticket.startswith("dev:") and len(ticket) > 4:
                return ticket[4:]
            raise HTTPException(401, "bad ticket")
        hit = ticket_cache.get(ticket)
        if hit and hit[1] > time.time():
            return hit[0]
        try:  # UNTESTED against the live Steam API: needs a publisher key. [verify]
            r = await client.get(STEAM_URL, params={"key": os.environ["STEAM_PUBLISHER_KEY"],
                                                    "appid": t["appid"], "ticket": ticket or ""})
            p = r.json().get("response", {}).get("params", {})
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "ticket check unavailable")
        if p.get("result") != "OK" or p.get("vacbanned") or p.get("publisherbanned"):
            raise HTTPException(401, "bad ticket")
        if len(ticket_cache) > 10_000:
            ticket_cache.clear()
        ticket_cache[ticket] = (p["steamid"], time.time() + 300)
        return p["steamid"]

    def sanitize(t, text):  # shortcut: regex blocklist only. A classifier is required before launch (gate G5).
        for pat in t.get("blocklist", []):
            if re.search(pat, text, re.I):
                return t.get("fallback_line", "..."), True
        return text[: t.get("max_reply_chars", 1000)], False

    @app.post("/v1/chat/completions")
    async def chat(req: Request, x_anansi_title: str = Header(None), x_anansi_key: str = Header(None),
                   x_steam_ticket: str = Header(None)):
        t = title_of(x_anansi_title, x_anansi_key)
        sid = await steam_id(t, x_steam_ticket)
        raw = await req.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "request too large")
        try:
            body = json.loads(raw)
            msgs = body["messages"]
            assert isinstance(msgs, list) and msgs and all(
                isinstance(m, dict) and isinstance(m.get("content"), str) and m.get("role") in ("system", "user", "assistant")
                for m in msgs)
        except Exception:
            raise HTTPException(400, "bad request body")
        if body.get("stream"):
            raise HTTPException(400, "streaming is not supported yet")
        if sum(len(m["content"]) for m in msgs) > t.get("max_prompt_chars", 8000):
            raise HTTPException(413, "prompt too long")

        day = datetime.datetime.now(datetime.timezone.utc)
        ukey = (x_anansi_title, sid, day.date())
        if usage.get(ukey, 0) >= t.get("daily_token_budget", 50_000):
            reset = (day + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return JSONResponse({"error": "daily token budget used"}, 429,
                                {"Retry-After": str(int((reset - day).total_seconds()))})

        meta = body.get("anansi") if isinstance(body.get("anansi"), dict) else {}
        up = {k: body[k] for k in FORWARD if k in body}
        up["model"] = body.get("model") or cfg["default_model"]
        up["max_tokens"] = min(int(body.get("max_tokens") or 10**9), t.get("max_tokens", 200))
        if t.get("system_prefix"):
            up["messages"] = [{"role": "system", "content": t["system_prefix"]}] + msgs
        structured = bool(meta.get("structured")) and bool(t.get("actions"))
        if structured:  # constrained decoding: the model can only emit whitelisted actions
            up["response_format"] = {"type": "json_schema", "json_schema": {"name": "npc_reply", "schema": {
                "type": "object", "additionalProperties": False, "required": ["say", "action"],
                "properties": {"say": {"type": "string"},
                               "action": {"type": "string", "enum": t["actions"] + ["none"]}}}}}

        npc = meta.get("npc_id")
        key = f"{x_anansi_title}:{npc}" if npc else None
        tried, data, node = [], None, None
        for _ in range(2):  # shortcut: fixed 2 attempts, replace with a retry budget (DESIGN.md 16.2)
            node = sched.pick(up["model"], key, exclude=tried)
            if node is None:
                break
            tried.append(node)
            sched.begin(node)
            t0 = time.monotonic()
            ok = False
            try:
                r = await client.post(node.url + "/v1/chat/completions", json=up)
                ok = r.status_code == 200
                data = r.json() if ok else None
            except (httpx.HTTPError, ValueError):
                data = None
            sched.end(node, ok and data is not None, (time.monotonic() - t0) * 1000)
            if data:
                break
        if not data:
            raise HTTPException(503, "no node available")

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise HTTPException(502, "bad node reply")
        filtered = False
        if structured:
            try:
                d = json.loads(text)
                say, act = str(d["say"]), d.get("action", "none")
            except Exception:
                say, act, filtered = t.get("fallback_line", "..."), "none", True
            if act not in t["actions"]:
                act = "none"
            say, f2 = sanitize(t, say)
            filtered = filtered or f2
            text = json.dumps({"say": say, "action": "none" if f2 else act})
        else:
            text, filtered = sanitize(t, text)

        used = (data.get("usage") or {}).get("total_tokens") or (sum(len(m["content"]) for m in msgs) + len(text)) // 4
        usage[ukey] = usage.get(ukey, 0) + int(used)
        return {"id": data.get("id", "anansi"), "object": "chat.completion", "model": up["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": data.get("usage"), "anansi": {"node": node.url, "filtered": filtered}}

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/admin/nodes")
    async def nodes(x_admin_token: str = Header(None)):
        want = os.environ.get("ANANSI_ADMIN_TOKEN")
        if not want or not hmac.compare_digest(want.encode(), (x_admin_token or "").encode()):
            raise HTTPException(404)
        return sched.snapshot()

    return app
