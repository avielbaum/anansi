"""Anansi gateway, Phase 1 MVP (DESIGN.md sections 1, 6, 11, 12).
OpenAI-compatible POST /v1/chat/completions in front of any OpenAI-compatible nodes
(vLLM, llama-server, the mock in tools/). Plain replies can stream sentence by sentence (stream: true); structured
actions are returned whole because the JSON must be complete before it can be checked."""
import datetime
import hmac
from collections import Counter, deque
import json
import os
import re
import time

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .scheduler import Scheduler

STEAM_URL = "https://partner.steam-api.com/ISteamUserAuth/AuthenticateUserTicket/v1/"
FORWARD = ("model", "messages", "temperature", "top_p")  # everything else is dropped on purpose
MAX_BODY = 64_000
RETRY_RATIO, RETRY_MIN, DECAY = 0.1, 3, 0.99  # decay 0.99 per request is a window of roughly 100 requests
THINK = re.compile(r"<think>.*?</think>", re.S)
SENT = re.compile(r".*?[.!?…]+[\"')\]]*\s+", re.S)  # one finished sentence plus the whitespace after it


def visible(raw):
    """Streamed text so far with reasoning removed (an unclosed <think> hides everything after it)."""
    return THINK.sub("", raw).split("<think>")[0].lstrip()


def leaks(prefix, text, n=5):
    """True if the reply repeats any run of n words from the studio's system prompt.
    shortcut: catches verbatim and near-verbatim leaks only, not a real paraphrase. Pair with a classifier (G5)."""
    w = lambda s: re.findall(r"\w+", s.lower())
    p, r = w(prefix), w(text)
    grams = {tuple(p[i:i + n]) for i in range(len(p) - n + 1)}
    return any(tuple(r[i:i + n]) in grams for i in range(len(r) - n + 1))


def reply_text(data):
    """Assistant text of an OpenAI-style reply, with leaked <think> blocks removed. Empty if missing."""
    try:
        return THINK.sub("", data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def make_app(config=None, transport=None):
    cfg = config or json.load(open(os.environ["ANANSI_CONFIG"], encoding="utf-8"))
    sched = Scheduler(cfg["nodes"])
    client = httpx.AsyncClient(transport=transport, timeout=cfg.get("upstream_timeout_s", 20))
    ticket_cache = {}  # shortcut: per-process caches, move to Redis when running more than one gateway
    usage = {}
    stats = {"requests": 0, "retries": 0, "status": Counter(), "filtered": 0, "stream_errors": 0, "lat_ms": deque(maxlen=1000)}
    budget = {"req": 0.0, "retry": 0.0}
    app = FastAPI()
    app.state.sched = sched

    @app.middleware("http")
    async def measure(req, call_next):  # records every outcome, including auth failures and 4xx/5xx
        t0 = time.monotonic()
        resp = await call_next(req)
        if req.url.path in ("/v1/chat/completions", "/v1/npc"):
            stats["status"][resp.status_code] += 1
            # a stream's latency is time to first sentence, recorded by the stream itself
            if resp.status_code == 200 and resp.media_type != "text/event-stream":
                stats["lat_ms"].append((time.monotonic() - t0) * 1000)
        return resp

    def admin(token):
        want = os.environ.get("ANANSI_ADMIN_TOKEN")
        if not want or not hmac.compare_digest(want.encode(), (token or "").encode()):
            raise HTTPException(404)

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

    def bad(t, text):  # shortcut: regex blocklist plus prompt-leak check. A classifier is required before launch (gate G5).
        return leaks(t.get("system_prefix", ""), text, t.get("leak_ngram", 5)) or any(
            re.search(p, text, re.I) for p in t.get("blocklist", []))

    def sanitize(t, text):
        if bad(t, text):
            return t.get("fallback_line", "..."), True
        return text[: t.get("max_reply_chars", 1000)], False

    def may_retry():  # retry budget: retries stay near 10% of recent traffic so a sick pool cannot multiply load
        if budget["retry"] >= RETRY_RATIO * budget["req"] + RETRY_MIN:
            return False
        stats["retries"] += 1
        budget["retry"] += 1
        return True

    def payload_for(up, node):
        p = {**up, **node.extra}
        if node.upstream_model:
            p["model"] = node.upstream_model
        return p

    async def stream_reply(t, up, key, ukey, prompt_chars):
        """SSE reply sent one finished sentence at a time, each checked before it leaves. Failover only while
        nothing has been sent. shortcut: sentences already sent cannot be recalled, so a leak or blocked word that
        shows up mid-reply cuts the stream off there instead of replacing the whole reply."""
        cap, fb = t.get("max_reply_chars", 1000), t.get("fallback_line", "...")
        sent, filtered, stop, node, tried, t_start, ttft = "", False, False, None, [], time.monotonic(), 0

        def sse(delta, fin=None, **extra):
            c = {"id": "anansi", "object": "chat.completion.chunk", "model": up["model"],
                 "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
            if extra:
                c["anansi"] = extra
            return f"data: {json.dumps(c)}\n\n"

        def advance(clean, final):  # sentences now safe to send; sets stop when the guard ends the stream
            nonlocal sent, filtered, stop
            out = []
            while not stop:
                pend = clean[len(sent):]
                m = SENT.match(pend)
                piece = m.group(0) if m else (pend if final else "")
                if not piece.strip():
                    break
                nxt = sent + piece
                if bad(t, nxt):
                    filtered = stop = True
                    if not sent:
                        out.append(fb)
                    break
                if len(nxt) > cap:
                    nxt, stop = nxt[:cap], True
                    piece = nxt[len(sent):]
                sent = nxt
                out.append(piece)
            return out

        for attempt in range(3):
            if attempt and (sent or filtered or not may_retry()):
                break
            node = sched.pick(up["model"], key, exclude=tried)
            if node is None:
                break
            tried.append(node)
            sched.begin(node)
            t0, ok, raw = time.monotonic(), False, ""
            try:
                async with client.stream("POST", node.url + "/v1/chat/completions",
                                         json={**payload_for(up, node), "stream": True}) as r:
                    if r.status_code != 200:
                        raise httpx.HTTPError("bad status")
                    async for line in r.aiter_lines():
                        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                            continue
                        try:
                            raw += json.loads(line[5:])["choices"][0]["delta"].get("content") or ""
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                            continue
                        for s in advance(visible(raw), False):
                            ttft = ttft or time.monotonic() - t_start
                            yield sse({"content": s})
                        if stop:
                            break
                for s in advance(visible(raw), True):
                    ttft = ttft or time.monotonic() - t_start
                    yield sse({"content": s})
                ok = bool(sent or filtered)  # an empty reply counts as a node failure
            except httpx.HTTPError:
                pass
            finally:
                sched.end(node, ok, (time.monotonic() - t0) * 1000)
            if ok or sent:
                break
        if sent or filtered:
            stats["lat_ms"].append(ttft * 1000)
            stats["filtered"] += filtered
            usage[ukey] = usage.get(ukey, 0) + (prompt_chars + len(sent)) // 4
            yield sse({}, "stop", node=node.url, filtered=filtered)
        else:
            stats["stream_errors"] += 1
            yield 'data: {"error": "no node available"}\n\n'
        yield "data: [DONE]\n\n"

    async def handle(req, x_anansi_title, x_anansi_key, x_steam_ticket, raw=None):
        t = title_of(x_anansi_title, x_anansi_key)
        sid = await steam_id(t, x_steam_ticket)
        raw = await req.body() if raw is None else raw
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

        stream = bool(body.get("stream"))
        if stream and structured:  # a JSON reply cannot be checked or shown until it is complete
            raise HTTPException(400, "streaming is only for plain replies, not structured actions")
        npc = meta.get("npc_id")
        key = f"{x_anansi_title}:{npc}" if npc else None
        stats["requests"] += 1
        budget["req"] = budget["req"] * DECAY + 1  # decayed counts: an old outage must not starve retries after recovery
        budget["retry"] *= DECAY
        if stream:
            return StreamingResponse(stream_reply(t, up, key, ukey, sum(len(m["content"]) for m in msgs)),
                                     media_type="text/event-stream")
        tried, data, node = [], None, None
        for attempt in range(3):
            if attempt and not may_retry():
                break
            node = sched.pick(up["model"], key, exclude=tried)
            if node is None:
                break
            tried.append(node)
            sched.begin(node)
            t0 = time.monotonic()
            ok = False
            try:
                r = await client.post(node.url + "/v1/chat/completions", json=payload_for(up, node))
                ok = r.status_code == 200
                data = r.json() if ok else None
            except (httpx.HTTPError, ValueError):
                data = None
            if data is not None and not reply_text(data):  # empty reply (e.g. a thinking model out of tokens) is a node failure
                data = None
            sched.end(node, ok and data is not None, (time.monotonic() - t0) * 1000)
            if data:
                break
        if not data:
            raise HTTPException(503, "no node available")

        text = reply_text(data)
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
        stats["filtered"] += filtered
        return {"id": data.get("id", "anansi"), "object": "chat.completion", "model": up["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": data.get("usage"), "anansi": {"node": node.url, "filtered": filtered}}

    @app.post("/v1/chat/completions")
    async def chat(req: Request, x_anansi_title: str = Header(None), x_anansi_key: str = Header(None),
                   x_steam_ticket: str = Header(None)):
        return await handle(req, x_anansi_title, x_anansi_key, x_steam_ticket)

    @app.post("/v1/npc")  # flat shape for game SDKs: Unity's JsonUtility cannot read the nested OpenAI shape
    async def npc(req: Request, x_anansi_title: str = Header(None), x_anansi_key: str = Header(None),
                  x_steam_ticket: str = Header(None)):
        try:
            d = json.loads(await req.body())
            want = bool(d.get("structured"))
            raw = json.dumps({"messages": d["messages"], "anansi": {"npc_id": d.get("npc_id") or None, "structured": want}})
        except Exception:
            raise HTTPException(400, "bad request body")
        r = await handle(req, x_anansi_title, x_anansi_key, x_steam_ticket, raw.encode())
        text, out = r["choices"][0]["message"]["content"], {"action": "none"}
        try:
            parsed = json.loads(text) if want else None
            out.update(say=parsed["say"], action=parsed["action"]) if isinstance(parsed, dict) else out.update(say=text)
        except (ValueError, KeyError):
            out["say"] = text
        return {**out, "filtered": r["anansi"]["filtered"], "node": r["anansi"]["node"]}

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/admin/nodes")
    async def nodes(x_admin_token: str = Header(None)):
        admin(x_admin_token)
        return sched.snapshot()

    @app.get("/admin/stats")
    async def get_stats(x_admin_token: str = Header(None)):
        admin(x_admin_token)
        lat = sorted(stats["lat_ms"])
        pct = lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))], 1) if lat else None
        return {"requests": stats["requests"], "retries": stats["retries"], "filtered": stats["filtered"],
                "stream_errors": stats["stream_errors"], "status": {str(k): v for k, v in stats["status"].items()},
                "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99), "samples": len(lat)}}

    return app
