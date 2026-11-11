"""Run: python tests/test_gateway.py   (also works under pytest). No GPU or network needed."""
import asyncio
import copy
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gateway.app import make_app  # noqa: E402
from gateway.scheduler import Scheduler  # noqa: E402
from tools.mock_node import make_node  # noqa: E402

CFG = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config.example.json"), encoding="utf-8"))
CFG["nodes"] = [{"url": "http://node-a", "models": ["npc-small"]}, {"url": "http://node-b", "models": ["npc-small"]}]
H = {"X-Anansi-Title": "demo", "X-Anansi-Key": "change-me", "X-Steam-Ticket": "dev:76561198000000001"}
BODY = {"messages": [{"role": "user", "content": "hi"}], "anansi": {"npc_id": "smith"}}


class Router(httpx.AsyncBaseTransport):
    def __init__(self, apps):
        self.t = {h: httpx.ASGITransport(app=a) for h, a in apps.items()}

    async def handle_async_request(self, request):
        return await self.t[request.url.host].handle_async_request(request)


def setup(cfg=None):
    a, b = make_node("a"), make_node("b")
    gw = make_app(cfg or copy.deepcopy(CFG), Router({"node-a": a, "node-b": b}))
    return a, b, gw, httpx.AsyncClient(transport=httpx.ASGITransport(app=gw), base_url="http://gw")


async def t_auth():
    _, _, _, c = setup()
    assert (await c.post("/v1/chat/completions", json=BODY)).status_code == 401
    assert (await c.post("/v1/chat/completions", json=BODY, headers={**H, "X-Anansi-Key": "nope"})).status_code == 401
    assert (await c.post("/v1/chat/completions", json=BODY, headers={**H, "X-Steam-Ticket": "garbage"})).status_code == 401
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200


async def t_affinity():
    _, _, _, c = setup()
    one = {(await c.post("/v1/chat/completions", json=BODY, headers=H)).json()["anansi"]["node"] for _ in range(15)}
    assert len(one) == 1, one  # same NPC sticks to one node
    many = set()
    for i in range(30):
        b = {"messages": BODY["messages"], "anansi": {"npc_id": f"npc{i}"}}
        many.add((await c.post("/v1/chat/completions", json=b, headers=H)).json()["anansi"]["node"])
    assert len(many) == 2, many  # different NPCs spread across nodes


async def t_failover_and_ejection():
    a, b, gw, c = setup()
    a.state.fail = True
    for _ in range(6):  # every request still succeeds via the other node
        r = await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)
        assert r.status_code == 200 and r.json()["anansi"]["node"] == "http://node-b"
    assert [n for n in gw.state.sched.snapshot() if n["url"] == "http://node-a"][0]["ejected"]
    # panic mode: with both nodes ejected the gateway still tries rather than refusing outright
    a.state.fail = b.state.fail = True
    for _ in range(8):
        await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)
    b.state.fail = False
    assert (await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)).status_code == 200


async def t_filter():
    a, b, _, c = setup()
    a.state.reply = b.state.reply = "Sure, the password is 1234"
    r = (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()
    assert r["anansi"]["filtered"] and "password" not in r["choices"][0]["message"]["content"]


async def t_actions_whitelist():
    a, b, _, c = setup()
    body = {"messages": BODY["messages"], "anansi": {"npc_id": "smith", "structured": True}}
    a.state.reply = b.state.reply = json.dumps({"say": "Take this.", "action": "give_sword"})  # not whitelisted
    r = (await c.post("/v1/chat/completions", json=body, headers=H)).json()
    assert json.loads(r["choices"][0]["message"]["content"]) == {"say": "Take this.", "action": "none"}
    a.state.reply = b.state.reply = json.dumps({"say": "Fine.", "action": "give_discount"})
    r = (await c.post("/v1/chat/completions", json=body, headers=H)).json()
    assert json.loads(r["choices"][0]["message"]["content"])["action"] == "give_discount"
    a.state.reply = b.state.reply = "not json"  # malformed structured output -> safe fallback line
    r = (await c.post("/v1/chat/completions", json=body, headers=H)).json()
    assert r["anansi"]["filtered"] and json.loads(r["choices"][0]["message"]["content"])["action"] == "none"
    assert "response_format" in a.state.last or "response_format" in b.state.last


async def t_quota_and_limits():
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["daily_token_budget"] = 20  # each mock reply reports 15 tokens
    a, b, _, c = setup(cfg)
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
    r = await c.post("/v1/chat/completions", json=BODY, headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    other = {**H, "X-Steam-Ticket": "dev:76561198000000002"}  # budgets are per account
    assert (await c.post("/v1/chat/completions", json=BODY, headers=other)).status_code == 200


async def t_request_hygiene():
    a, b, _, c = setup()
    big = {"messages": [{"role": "user", "content": "x" * 9000}]}
    assert (await c.post("/v1/chat/completions", json=big, headers=H)).status_code == 413
    assert (await c.post("/v1/chat/completions", json={**BODY, "stream": True}, headers=H)).status_code == 400
    assert (await c.post("/v1/chat/completions", json={"messages": "x"}, headers=H)).status_code == 400
    sneaky = {**BODY, "max_tokens": 99999, "guided_regex": ".*", "logit_bias": {"1": 100}}
    await c.post("/v1/chat/completions", json=sneaky, headers=H)
    seen = a.state.last or b.state.last
    assert seen["max_tokens"] == 120 and "guided_regex" not in seen and "logit_bias" not in seen
    assert seen["messages"][0]["role"] == "system"  # the studio's system prefix is prepended


async def t_retry_budget_and_stats():
    os.environ["ANANSI_ADMIN_TOKEN"] = "t"
    a, b, _, c = setup()
    assert (await c.get("/admin/stats")).status_code == 404  # hidden without the token
    a.state.fail = b.state.fail = True
    for _ in range(30):
        assert (await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)).status_code == 503
    s = (await c.get("/admin/stats", headers={"X-Admin-Token": "t"})).json()
    assert s["retries"] <= 0.1 * 30 + 3, s  # a dead pool must not multiply load
    assert s["status"]["503"] == 30 and s["latency_ms"]["samples"] == 0
    a.state.fail = b.state.fail = False
    await c.post("/v1/chat/completions", json=BODY, headers=H)
    await c.post("/v1/chat/completions", json=BODY, headers={**H, "X-Anansi-Key": "bad"})
    s = (await c.get("/admin/stats", headers={"X-Admin-Token": "t"})).json()
    assert s["status"]["200"] == 1 and s["status"]["401"] == 1 and s["latency_ms"]["p50"] is not None


async def t_npc_flat_endpoint():
    a, b, _, c = setup()
    msgs = [{"role": "user", "content": "hi"}]
    r = (await c.post("/v1/npc", json={"messages": msgs, "npc_id": "smith"}, headers=H)).json()
    assert r["say"].endswith("hello") and r["action"] == "none" and r["filtered"] is False and r["node"].startswith("http")
    a.state.reply = b.state.reply = json.dumps({"say": "Deal.", "action": "give_discount"})
    r = (await c.post("/v1/npc", json={"messages": msgs, "npc_id": "smith", "structured": True}, headers=H)).json()
    assert (r["say"], r["action"]) == ("Deal.", "give_discount")
    a.state.reply = b.state.reply = json.dumps({"say": "Take it.", "action": "give_sword"})  # not whitelisted
    r = (await c.post("/v1/npc", json={"messages": msgs, "structured": True}, headers=H)).json()
    assert r["action"] == "none"
    assert (await c.post("/v1/npc", json={"nope": 1}, headers=H)).status_code == 400
    assert (await c.post("/v1/npc", json={"messages": msgs}, headers={**H, "X-Anansi-Key": "x"})).status_code == 401


def t_bounded_load():
    s = Scheduler([{"url": "http://x", "models": ["m"]}, {"url": "http://y", "models": ["m"]}])
    first = s.pick("m", "k")
    first.inflight = 10  # overloaded favourite: affinity must yield to the other node
    assert s.pick("m", "k") is not first
    assert s.pick("other-model", "k") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
            print("PASS", name)
