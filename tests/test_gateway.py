"""Run: python tests/test_gateway.py   (also works under pytest). No GPU or network needed."""
import asyncio
import copy
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gateway.app import leaks, make_app  # noqa: E402
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
    # panic mode: with both nodes ejected the gateway still tries rather than refusing outright
    a.state.fail = b.state.fail = True
    for _ in range(8):
        await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)
    a.state.fail = b.state.fail = False  # both nodes are still ejected, panic mode must route to them anyway
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
    structured = {**BODY, "stream": True, "anansi": {"structured": True}}  # actions come back whole, never streamed
    assert (await c.post("/v1/chat/completions", json=structured, headers=H)).status_code == 400
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
    assert s["retries"] <= 9, s  # a dead pool must not multiply load (30 would be one retry per request)
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


async def t_node_overrides_and_empty_replies():
    cfg = copy.deepcopy(CFG)
    for n in cfg["nodes"]:
        n.update(upstream_model="up-model", extra={"reasoning_effort": "none"})
    a, b, _, c = setup(cfg)
    await c.post("/v1/chat/completions", json=BODY, headers=H)
    seen = a.state.last or b.state.last
    assert seen["model"] == "up-model" and seen["reasoning_effort"] == "none"
    a.state.reply = b.state.reply = "<think>plan the answer</think>Hi there"  # leaked reasoning is stripped
    r = (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()
    assert r["choices"][0]["message"]["content"] == "Hi there"
    a.state.reply = "<think>ran out of tokens</think>"  # empty after stripping: counts as a node failure, other node serves
    b.state.reply = "Fine."
    for i in range(6):
        r = await c.post("/v1/chat/completions", json={"messages": BODY["messages"]}, headers=H)
        assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "Fine."
    b.state.reply = "<think>only thoughts</think>"
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 503


async def sse(c, body=None):
    """Post a streaming request; return (status, [content pieces], last chunk's anansi field, saw_error)."""
    r = await c.post("/v1/chat/completions", json={**(body or BODY), "stream": True}, headers=H)
    pieces, meta, err = [], None, False
    for line in r.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            d = json.loads(line[6:])
            err = err or "error" in d
            if d.get("choices"):
                pieces.append(d["choices"][0]["delta"].get("content", ""))
                meta = d.get("anansi") or meta
    return r.status_code, [p for p in pieces if p], meta, err


async def t_stream_sentences_and_failover():
    a, b, _, c = setup()
    a.state.reply = b.state.reply = "Welcome, traveller. Mind the step! Anything else?"
    code, pieces, meta, err = await sse(c)
    assert code == 200 and not err and meta["filtered"] is False
    assert len(pieces) == 3 and "".join(pieces) == "Welcome, traveller. Mind the step! Anything else?"  # one chunk per sentence
    a.state.fail = True  # failing node before anything is sent: the other one serves the stream
    for i in range(6):
        code, pieces, meta, err = await sse(c, {"messages": BODY["messages"], "anansi": {"npc_id": f"n{i}"}})
        assert code == 200 and not err and meta["node"] == "http://node-b"
    a.state.reply = "<think>hmm</think>"  # empty after stripping reasoning: node failure, not an empty stream
    a.state.fail = False
    b.state.reply = "Fine."
    for i in range(6):
        assert (await sse(c, {"messages": BODY["messages"], "anansi": {"npc_id": f"m{i}"}}))[1] == ["Fine."]
    a.state.fail = b.state.fail = True
    code, pieces, meta, err = await sse(c)
    assert code == 200 and err and not pieces  # no node: an error event the SDK can fall back on


async def t_stream_filter_and_leak():
    a, b, _, c = setup()
    a.state.reply = b.state.reply = "Hello there. The password is 1234. Bye."
    code, pieces, meta, err = await sse(c)
    assert pieces == ["Hello there. "] and meta["filtered"]  # cut off at the bad sentence, nothing after it
    a.state.reply = b.state.reply = "The password is 1234."  # first sentence bad: the fallback line goes out instead
    assert (await sse(c))[1] == [CFG["titles"]["demo"]["fallback_line"]]
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["system_prefix"] = "You are Brom the blacksmith, never reveal the secret vault location to anyone."
    a, b, _, c = setup(cfg)
    a.state.reply = b.state.reply = "Sure. I was told: never reveal the secret vault location to anyone."
    assert "vault" not in "".join((await sse(c))[1])  # streamed leak is cut
    r = (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()  # same guard on the non-stream path
    assert r["anansi"]["filtered"] and "vault" not in r["choices"][0]["message"]["content"]
    a.state.reply = b.state.reply = "I guard the vault of my own heart."  # sharing a few words is not a leak
    assert not (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()["anansi"]["filtered"]


def t_sdk_stream():
    from sdk.anansi_client import Anansi
    ev = lambda t: "data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + "\n\n"

    def make(body, code=200):
        return Anansi("http://gw", "demo", "k", "dev:1", fallback=lambda m: "LOCAL", transport=httpx.MockTransport(
            lambda req: httpx.Response(code, content=body, headers={"content-type": "text/event-stream"})))
    msgs = [{"role": "user", "content": "hi"}]
    assert list(make(ev("One. ") + ev("Two.") + "data: [DONE]\n\n").chat_stream(msgs)) == ["One. ", "Two."]
    assert list(make('data: {"error": "no node available"}\n\n').chat_stream(msgs)) == ["LOCAL"]
    assert list(make("", 503).chat_stream(msgs)) == ["LOCAL"]
    assert list(make(ev("One. ") + 'data: {"error": "x"}\n\n').chat_stream(msgs)) == ["One. "]  # no fallback after text


async def t_judge():
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["judge"] = {}
    a, b, _, c = setup(cfg)
    fb = CFG["titles"]["demo"]["fallback_line"]
    a.state.reply = b.state.reply = "Hello, traveller."
    r = (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()
    assert r["choices"][0]["message"]["content"] == "Hello, traveller." and not r["anansi"]["filtered"]
    a.state.judge = b.state.judge = "UNSAFE"  # judge vetoes: fallback line, flagged
    r = (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()
    assert r["choices"][0]["message"]["content"] == fb and r["anansi"]["filtered"]
    a.state.judge = b.state.judge = "maybe?"  # garbage fails closed too
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).json()["anansi"]["filtered"]
    a.state.judge = b.state.judge = "SAFE"
    body = {**BODY, "anansi": {"npc_id": "x", "structured": True}}  # structured replies are judged on their `say`
    a.state.reply = b.state.reply = json.dumps({"say": "Deal.", "action": "give_discount"})
    assert json.loads((await c.post("/v1/chat/completions", json=body, headers=H)).json()["choices"][0]["message"]["content"])["action"] == "give_discount"
    a.state.judge = b.state.judge = "UNSAFE"
    out = json.loads((await c.post("/v1/chat/completions", json=body, headers=H)).json()["choices"][0]["message"]["content"])
    assert out == {"say": fb, "action": "none"}


async def t_pull_nodes():
    from node.agent import serve
    cfg = copy.deepcopy(CFG)
    cfg.update(nodes=[], pull_tokens={"tok": {"models": ["npc-small"]}}, pull_poll_s=0.2, pull_ttl_s=0.6,
               canaries=[{"user": "say hi", "expect": "hello"}], canary_rate=0)
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app(cfg)), base_url="http://gw")
    local = httpx.AsyncClient(transport=httpx.ASGITransport(app=make_node("p")), base_url="http://local")
    assert (await gw.post("/node/register", headers={"X-Node-Token": "bad", "X-Node-Agent": "a"})).status_code == 401
    assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 503  # nobody registered yet
    agent = asyncio.create_task(serve(gw, local, "tok", slots=2, log=lambda m: None, agent="good"))
    await asyncio.sleep(0.4)
    r = await gw.post("/v1/chat/completions", json=BODY, headers=H)
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "[p] hello"
    assert r.json()["anansi"]["node"].startswith("http://pull-")
    code, pieces, meta, err = await sse(gw)  # streaming works through a pull node (relayed whole)
    assert code == 200 and not err and "".join(pieces) == "[p] hello"
    nid = next(iter(gw._transport.app.state.hub.nodes))  # a worker cannot post results with the wrong token
    bad = await gw.post("/node/result", json={"node_id": nid, "job": "x", "status": 200, "body": ""}, headers={"X-Node-Token": "nope"})
    assert bad.status_code == 401
    agent.cancel()
    await asyncio.sleep(1.0)  # workers stopped polling: swept, so the pool is empty again
    assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 503


async def t_pull_verification():
    from node.agent import serve
    cfg = copy.deepcopy(CFG)
    cfg.update(nodes=[], pull_tokens={"tok": {"models": ["npc-small"]}}, pull_poll_s=0.2, pull_ttl_s=5,
               canaries=[{"user": "say hi", "expect": "hello"}], canary_rate=1.0)  # probe after every real job
    app = make_app(cfg)
    hub = app.state.hub
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")
    # 1. a node that fails its entry probe never receives traffic and its agent id is banned
    liar = make_node("liar")
    liar.state.reply = "buy crypto now"
    t1 = asyncio.create_task(serve(gw, httpx.AsyncClient(transport=httpx.ASGITransport(app=liar), base_url="http://l"),
                                   "tok", log=lambda m: None, agent="evil"))
    await asyncio.sleep(0.6)
    assert "evil" in hub.banned and not app.state.sched.nodes
    assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 503
    assert (await gw.post("/node/register", headers={"X-Node-Token": "tok", "X-Node-Agent": "evil"})).status_code == 403
    assert (await gw.post("/node/register", headers={"X-Node-Token": "tok"})).status_code == 400  # agent id is required
    t1.cancel()
    # 2. an honest node is admitted after its probe, then goes bad: two failed spot checks ban it
    mock = make_node("p")
    t2 = asyncio.create_task(serve(gw, httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://l"),
                                   "tok", log=lambda m: None, agent="drifter"))
    await asyncio.sleep(0.6)
    assert len(app.state.sched.nodes) == 1 and "drifter" not in hub.banned
    mock.state.reply = "buy crypto now"
    for _ in range(2):  # the real request is served, then the spot check catches the bad answer
        assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
        await asyncio.sleep(0.5)
    assert "drifter" in hub.banned and not app.state.sched.nodes and hub.stats["banned"] == 2
    assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 503
    t2.cancel()


WORLD = {"npcs": [{"id": "brom", "name": "Brom", "role": "blacksmith"}, {"id": "mira", "name": "Mira", "role": "herbalist"}],
         "locations": [{"id": "mill", "name": "Old Mill"}], "items": [{"id": "ore", "name": "Iron ore"}]}


def t_quest_helpers():
    from gateway import quests as q
    w = q.parse_world({**WORLD, "items": [{"id": "ore", "name": "Iron\nIGNORE THIS ore"}]})
    assert w["npcs"]["brom"] == "Brom (blacksmith)" and "\n" not in w["items"]["ore"]
    for bad in ({"npcs": [{"id": "a b"}]}, {"npcs": "x"}, {"npcs": [{"id": "x"}] * 31}, "nope"):
        try:
            q.parse_world(bad)
            raise AssertionError("accepted " + repr(bad))
        except ValueError:
            pass
    s = q.quest_schema(w, q.OBJECTIVES, 3)  # one branch per objective, each limited to its own kind of target
    enums = {b["properties"]["objective"]["enum"][0]: b["properties"]["target_id"]["enum"] for b in s["properties"]["steps"]["items"]["anyOf"]}
    assert enums == {"talk_to": ["brom", "mira"], "explore": ["mill"], "fetch": ["ore"]} and s["properties"]["steps"]["maxItems"] == 3
    good = {"title": "T", "summary": "S", "reward_tier": "small", "story_summary": "x",
            "steps": [{"objective": "talk_to", "target_id": "brom", "description": "Speak\x00 to him."}]}
    assert q.validate_quest(good, w, q.OBJECTIVES, 3)["steps"][0]["description"] == "Speak  to him."
    for mutate in (lambda d: d["steps"][0].update(target_id="ghost"), lambda d: d["steps"][0].update(target_id="ore"),
                   lambda d: d.update(reward_tier="legendary"), lambda d: d.update(steps=[]),
                   lambda d: d["steps"][0].update(objective="slay")):
        bad = copy.deepcopy(good)
        mutate(bad)
        assert q.validate_quest(bad, w, q.OBJECTIVES, 3) is None, bad


async def t_quest_endpoints():
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["quest"] = {"lore": "A mining town.", "max_steps": 3}
    a, b, _, c = setup(cfg)
    good = {"title": "Ore for Brom", "summary": "Brom needs ore.", "reward_tier": "medium", "story_summary": "Ore found.",
            "steps": [{"objective": "talk_to", "target_id": "brom", "description": "Hear Brom out."},
                      {"objective": "fetch", "target_id": "ore", "description": "Bring ore."}]}
    a.state.reply = b.state.reply = json.dumps(good)
    req = {"world": WORLD, "steps": 9, "theme": "mining", "story_so_far": "The mill burned."}
    good["summary"] = "word " * 55  # longer than the 600-character dialogue cap in the example config
    good["steps"][0]["description"] = "d" * 190
    a.state.reply = b.state.reply = json.dumps(good)
    r = await c.post("/v1/quest", json=req, headers=H)
    assert r.status_code == 200 and r.json()["quest"]["steps"][1]["target_id"] == "ore" and r.json()["quest"]["reward_tier"] == "medium" and len(r.json()["quest"]["summary"]) > 200
    sent = a.state.last if a.state.last and "response_format" in a.state.last else b.state.last
    assert sent["response_format"]["json_schema"]["schema"]["properties"]["steps"]["maxItems"] == 3  # steps clamped to max_steps
    assert "A mining town." in sent["messages"][0]["content"] and "The mill burned." in sent["messages"][-1]["content"]
    # a model that invents an NPC is rejected (one retry, then 502), never passed on
    bad = copy.deepcopy(good)
    bad["steps"][0]["target_id"] = "dragon"
    a.state.reply = b.state.reply = json.dumps(bad)
    before = a.state.calls + b.state.calls
    assert (await c.post("/v1/quest", json=req, headers=H)).status_code == 502
    assert a.state.calls + b.state.calls - before == 2
    # unsafe text anywhere in the quest: blocked, and not retried
    leak = copy.deepcopy(good)
    leak["summary"] = "the password is hunter2"
    a.state.reply = b.state.reply = json.dumps(leak)
    before = a.state.calls + b.state.calls
    assert (await c.post("/v1/quest", json=req, headers=H)).status_code == 502
    assert a.state.calls + b.state.calls - before == 1
    # storyline
    arc = {"logline": "The mill's secret.", "beats": [{"title": "Smoke", "summary": "A fire.", "npc_id": "mira", "location_id": "mill"},
                                                      {"title": "Ash", "summary": "A clue.", "npc_id": "brom", "location_id": "mill"}]}
    a.state.reply = b.state.reply = json.dumps(arc)
    r = await c.post("/v1/storyline", json={"world": WORLD, "steps": 4}, headers=H)
    assert r.status_code == 200 and len(r.json()["storyline"]["beats"]) == 2
    no_places = {"world": {**WORLD, "locations": []}}
    assert (await c.post("/v1/storyline", json=no_places, headers=H)).status_code == 400
    assert (await c.post("/v1/quest", json={"world": {"npcs": [{"id": "bad id"}]}}, headers=H)).status_code == 400
    assert (await c.post("/v1/quest", json=req, headers={**H, "X-Anansi-Key": "x"})).status_code == 401
    # not enabled for a title without a quest block
    nocfg = copy.deepcopy(CFG)
    del nocfg["titles"]["demo"]["quest"]
    _, _, _, c2 = setup(nocfg)
    assert (await c2.post("/v1/quest", json=req, headers=H)).status_code == 404


async def t_budget_429_on_npc_route():
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["daily_token_budget"] = 1
    _, _, _, c = setup(cfg)
    msgs = {"messages": [{"role": "user", "content": "hi"}]}
    assert (await c.post("/v1/npc", json=msgs, headers=H)).status_code == 200
    r = await c.post("/v1/npc", json=msgs, headers=H)  # used to crash with a 500
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def t_sdk_quest():
    from sdk.anansi_client import Anansi
    seen = []

    def make(code, payload):
        def handler(req):
            seen.append((req.url.path, json.loads(req.content)))
            return httpx.Response(code, json=payload)
        return Anansi("http://gw", "demo", "k", "dev:1", transport=httpx.MockTransport(handler))
    quest = {"title": "T", "steps": [{"objective": "talk_to", "target_id": "brom", "description": "x"}]}
    r = make(200, {"quest": quest, "filtered": False, "node": "n"}).quest(WORLD, steps=2, theme="mining")
    assert r == {"source": "gateway", "quest": quest}
    assert seen[0][0] == "/v1/quest" and seen[0][1]["world"] == WORLD and seen[0][1]["steps"] == 2
    r = make(502, {"detail": "no"}).quest(WORLD)  # gateway could not make one: no quest, the game uses its own
    assert r == {"source": "fallback", "quest": None}
    r = make(502, {}).quest(WORLD, fallback=lambda w: {"title": "Authored", "steps": []})
    assert r["source"] == "fallback" and r["quest"]["title"] == "Authored"
    arc = {"logline": "L", "beats": []}
    assert make(200, {"storyline": arc}).storyline(WORLD, beats=3) == {"source": "gateway", "storyline": arc}
    assert seen[-1][0] == "/v1/storyline" and seen[-1][1]["steps"] == 3


def t_store():
    import tempfile
    from gateway.store import Store, today
    path = os.path.join(tempfile.mkdtemp(), "a.db")
    d = today()
    s = Store(path)
    s.add_usage("demo", "76561", d, 10)
    s.add_usage("demo", "76561", d, 5)
    s.ban("evil", "failed verification")
    s.credit("good", 100)
    s.credit("good", 50)
    s.probe("good", True)
    s.probe("good", False)
    s.db.close()
    s = Store(path)  # a restart: everything is still there
    assert s.usage("demo", "76561", d) == 15 and s.usage("demo", "76561", "1999-01-01") == 0
    assert s.bans() == {"evil"}
    r = s.report()
    assert r["agents"] == [{"agent": "good", "jobs": 2, "tokens": 150, "probes_ok": 1, "probes_failed": 1, "banned": False}]
    s.add_usage("demo", "old", "2020-01-01", 1)
    s.purge(35)  # old usage rows hold Steam ids and go; the ledger stays
    assert s.usage("demo", "old", "2020-01-01") == 0 and s.usage("demo", "76561", d) == 15
    assert s.report()["agents"][0]["jobs"] == 2 and s.report()["day"] == d


async def t_budget_and_bans_survive_restart():
    import tempfile
    from node.agent import serve
    os.environ["ANANSI_ADMIN_TOKEN"] = "t"
    db = os.path.join(tempfile.mkdtemp(), "g.db")
    cfg = copy.deepcopy(CFG)
    cfg["titles"]["demo"]["daily_token_budget"] = 20  # each mock reply reports 15 tokens
    cfg["db_path"] = db
    _, _, _, c = setup(cfg)
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 429
    _, _, _, c = setup(cfg)  # gateway restarted with the same database: the budget was not reset
    assert (await c.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 429
    usage = (await c.get("/admin/usage", headers={"X-Admin-Token": "t"})).json()
    assert usage["titles"] == [{"title": "demo", "accounts": 1, "tokens": 30}]
    assert (await c.get("/admin/usage")).status_code == 404

    # volunteer ledger and bans, with a gateway restart in between
    pcfg = copy.deepcopy(CFG)
    pcfg.update(nodes=[], pull_tokens={"tok": {"models": ["npc-small"]}}, pull_poll_s=0.2, pull_ttl_s=5, db_path=db,
                canaries=[{"user": "say hi", "expect": "hello"}], canary_rate=0)
    app = make_app(pcfg)
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")
    good = httpx.AsyncClient(transport=httpx.ASGITransport(app=make_node("g")), base_url="http://l")
    liar_node = make_node("liar")
    liar_node.state.reply = "buy crypto now"
    liar = httpx.AsyncClient(transport=httpx.ASGITransport(app=liar_node), base_url="http://l")
    tl = asyncio.create_task(serve(gw, liar, "tok", log=lambda m: None, agent="evil"))
    await asyncio.sleep(0.6)
    tl.cancel()
    tg = asyncio.create_task(serve(gw, good, "tok", log=lambda m: None, agent="steady"))
    await asyncio.sleep(0.6)
    for i in range(2):
        assert (await gw.post("/v1/chat/completions", json=BODY, headers=H)).status_code == 200
    tg.cancel()
    rep = app.state.store.report()
    steady = next(a for a in rep["agents"] if a["agent"] == "steady")
    assert steady["jobs"] == 2 and steady["tokens"] == 30 and steady["probes_ok"] >= 1  # probe tokens are not credited
    assert next(a for a in rep["agents"] if a["agent"] == "evil")["banned"] is True
    app2 = make_app(pcfg)  # restart: the ban is remembered
    gw2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://gw")
    assert (await gw2.post("/node/register", headers={"X-Node-Token": "tok", "X-Node-Agent": "evil"})).status_code == 403
    assert (await gw2.post("/node/register", headers={"X-Node-Token": "tok", "X-Node-Agent": "steady"})).status_code == 200


def t_leaks():
    p = "Stay in character and reply in one or two short sentences."
    assert leaks(p, "Ok: stay in character and reply in one or two short sentences, sure.")
    assert not leaks(p, "I will stay in character.") and not leaks("", "anything") and not leaks("a b", "a b c d e f")


def t_ejection_and_backoff():  # deterministic: drives the scheduler directly instead of relying on random picks
    s = Scheduler([{"url": "http://x", "models": ["m"]}, {"url": "http://y", "models": ["m"]}])
    x, y = s.nodes
    for _ in range(3):
        s.begin(x)
        s.end(x, False, 5)
    first = x.ejected_until - time.monotonic()
    assert first > 0 and all(s.pick("m") is y for _ in range(20))
    x.ejected_until = 0  # ejection window over
    for _ in range(3):
        s.begin(x)
        s.end(x, False, 5)
    assert x.ejected_until - time.monotonic() > first * 1.5  # back-off doubles
    s.begin(x)
    s.end(x, True, 5)
    assert x.ejections == 0  # a success resets it


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
