"""Pull nodes: volunteer machines behind NAT connect OUT to the gateway and poll for work (DESIGN.md section 3).
To the scheduler each registered worker is an ordinary Node at http://pull-<id>.node; this transport turns the
gateway's request to that address into a job a polling agent picks up, so routing, failover, ejection and the
retry budget all work unchanged.
Verification: a new worker must pass a known-answer probe before it receives real traffic, and live workers are
probed at random after real jobs. A wrong answer is a strike; a failed entry probe or two strikes ban the agent id.
The probe looks like any chat request, but a node that fingerprints it (no system prompt, short, a few fixed
questions) can still cheat. Quorum on real answers is not built: free text differs across hardware.
A ban covers the agent id and, for a per-volunteer token, the token (stored as a hash), so a new id does not help.
shortcut: with a token marked "shared" the ban is by self-chosen agent id only (a Sybil can mint new ones), and an
operator can still ask for new tokens: real identity needs platform-bound certificates, DESIGN 9. Worker queues are in memory, so an agent registers with every gateway machine itself (agent --gateway a,b); a streamed request is answered whole by the agent
(the SSE text is relayed after the node finishes), so streaming from a pull node is correct but not incremental."""
import asyncio
import hashlib
import hmac
import json
import random
import re
import secrets
import time

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .leaderboard import clean_telemetry, name_problem
from .scheduler import Node
from .store import Store

CANARIES = [  # known answers a working model gets right at temperature 0; matched by regex, not equality
    {"user": "What is 17 plus 25? Reply with only the number.", "expect": r"\b42\b"},
    {"user": "Reply with only the word ORANGE in capital letters.", "expect": r"^\W*ORANGE\W*$"},  # the whole reply: echoing the question must not pass
    {"user": "What is the capital of France? Answer in one word.", "expect": r"Paris"},
]
STRIKES = 2
MAX_RESULT = 512_000  # bytes a volunteer may send back for one job
TELEMETRY_MIN_S = 20  # a machine's reports are stored at most this often; the agent sends one every 5 minutes


class PullHub(httpx.AsyncBaseTransport):
    def __init__(self, sched, tokens, inner, poll_s=20, ttl_s=None, job_timeout_s=60, reply_text=None,
                 canaries=None, canary_rate=0.05, store=None, rates=None, leaderboard=None):
        self.sched, self.tokens, self.inner = sched, tokens, inner
        self.rates = rates or {}  # credits per 1,000 tokens by the model name sent to the node; "default" for the rest
        self.poll_s, self.job_timeout_s = poll_s, job_timeout_s
        self.ttl_s = ttl_s if ttl_s is not None else poll_s + 15  # must outlast one long poll
        self.reply_text, self.canaries, self.canary_rate = reply_text, canaries or CANARIES, canary_rate
        self.store = store or Store()  # bans live only here: they survive a restart and other processes see them
        self.stats = {"probes": 0, "probe_failures": 0, "probe_no_answer": 0, "banned": 0}
        self.nodes = {}  # id -> {"node", "token", "agent", "q", "seen", "live", "strikes"}
        self.jobs = {}   # job id -> (node id, Future)
        self.tele_seen = {}  # agent id -> when its last report was stored
        self.lb = leaderboard or {}  # the gateway's `leaderboard` config block

    def check(self, token, agent):
        """(token config, token ban id) for a known token and an agent that is not banned; raises otherwise."""
        if not agent or len(agent) > 64:
            raise HTTPException(400, "X-Node-Agent id required")
        cfg = next((c for t, c in self.tokens.items() if hmac.compare_digest(t.encode(), (token or "").encode())), None)
        if cfg is None:
            raise HTTPException(401, "bad node token")
        # A failed check bans the token too, unless the token is marked shared (one pool token for everyone, where a ban
        # would lock out every volunteer): then only the self-chosen agent id is banned, and a new id gets round it.
        tid = None if cfg.get("shared") else "token:" + hashlib.sha256(token.encode()).hexdigest()[:16]
        bans = self.store.bans()
        if agent in bans or tid in bans:
            raise HTTPException(403, "agent banned")
        return cfg, tid

    def link_code(self, token, agent, ttl_s=600):
        """A one-time code the volunteer types into a game to link this machine to their player account."""
        self.check(token, agent)
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))  # no 0/O or 1/I
        self.store.add_link_code(code, agent, ttl_s)
        return {"code": code[:4] + "-" + code[4:], "expires_s": ttl_s}

    def report(self, token, agent, data):
        """Store what a machine reported about itself for the leaderboard (an opt-in, see gateway/leaderboard.py). Only a machine that has
        registered or has served a job may: a made-up agent id cannot put a row on the board. Returns (stored, why the display name was
        refused or ""): stored is False if the report came too soon after the last; a refused name is left out and the rest is kept."""
        self.check(token, agent)
        if not self.lb.get("enabled", True):
            raise HTTPException(403, "the leaderboard is switched off on this gateway")
        if self.store.blocked("node", agent):
            raise HTTPException(403, "the operator has blocked this machine from the leaderboard")
        if not self.store.has_work(agent) and not any(e["agent"] == agent for e in self.nodes.values()):
            raise HTTPException(403, "register first: only machines that have registered or served jobs can report")
        now = time.monotonic()
        if now - self.tele_seen.get(agent, -1e9) < TELEMETRY_MIN_S:
            return False, ""
        if len(self.tele_seen) > 10_000:
            self.tele_seen.clear()
        self.tele_seen[agent] = now
        problem = name_problem(data["name"], self.lb.get("blocked_names", []))
        self.store.set_telemetry(agent, {**data, "name": "" if problem else data["name"]})
        return True, problem

    def register(self, token, agent):
        cfg, tid = self.check(token, agent)
        if sum(e["token"] == token for e in self.nodes.values()) >= cfg.get("max_workers", 8):
            raise HTTPException(429, "too many workers on this token")  # one token cannot flood the pool
        nid = secrets.token_hex(6)
        node = Node(f"http://pull-{nid}.node", cfg["models"], cfg.get("region", "volunteer"),
                    cfg.get("upstream_model"), cfg.get("extra"), volunteer=True)
        # not in the scheduler yet: it joins after passing its entry probe
        self.nodes[nid] = {"node": node, "token": token, "tid": tid, "agent": agent, "q": asyncio.Queue(),
                           "seen": time.monotonic(), "live": False, "strikes": 0}
        asyncio.get_running_loop().create_task(self.probe(nid))
        return nid

    def entry(self, nid, token):
        e = self.nodes.get(nid)
        if e is None:
            raise HTTPException(404, "unknown node, register again")
        if not hmac.compare_digest(e["token"].encode(), (token or "").encode()):
            raise HTTPException(401, "bad node token")
        return e

    def drop(self, nid):
        e = self.nodes.pop(nid, None)
        if e is None:
            return
        if e["live"]:
            self.sched.nodes.remove(e["node"])
        for jid, (n, fut) in list(self.jobs.items()):
            if n == nid and not fut.done():
                fut.set_exception(httpx.ConnectError("node left"))

    def sweep(self):  # forget workers that stopped polling
        now = time.monotonic()
        for nid, e in list(self.nodes.items()):
            if now - e["seen"] > self.ttl_s:
                self.drop(nid)

    async def poll(self, nid, token):
        e = self.entry(nid, token)
        e["seen"] = time.monotonic()
        try:
            job = await asyncio.wait_for(e["q"].get(), self.poll_s)
        except asyncio.TimeoutError:
            job = None
        e["seen"] = time.monotonic()
        return job

    def finish(self, nid, token, jid, status, body, ctype):
        self.entry(nid, token)
        owner, fut = self.jobs.get(jid, (None, None))
        if owner != nid:
            raise HTTPException(404, "unknown job")
        if not fut.done():
            fut.set_result((status, body, ctype))

    async def dispatch(self, nid, path, body):
        """Queue one job for a worker and wait for its answer: (status, text, content-type)."""
        e = self.nodes.get(nid)
        if e is None:
            raise httpx.ConnectError("node gone")
        jid = secrets.token_hex(8)
        fut = asyncio.get_running_loop().create_future()
        self.jobs[jid] = (nid, fut)
        e["q"].put_nowait({"job": jid, "path": path, "body": body})
        try:
            return await asyncio.wait_for(fut, self.job_timeout_s)
        except asyncio.TimeoutError:
            raise httpx.ReadTimeout("node timed out")
        finally:
            self.jobs.pop(jid, None)

    async def probe(self, nid):
        """Known-answer check. A wrong answer is a strike; unreachable or error replies are not (the scheduler's
        ejection handles those). Passing admits a new worker to the pool."""
        e = self.nodes.get(nid)
        if e is None:
            return
        c = random.choice(self.canaries)
        node = e["node"]
        body = json.dumps({"model": node.upstream_model or sorted(node.models)[0], **node.extra,
                           "messages": [{"role": "user", "content": c["user"]}], "max_tokens": 30, "temperature": 0})
        try:
            status, text, _ = await self.dispatch(nid, "/v1/chat/completions", body)
        except httpx.HTTPError:
            return
        if status != 200:
            return
        self.stats["probes"] += 1
        ok = False
        try:
            answer = self.reply_text(json.loads(text))
        except ValueError:
            answer = ""
        answer = answer.split("<think>")[0].strip()  # a reasoning block cut off by the token cap holds no answer yet
        if not answer:  # no verdict: a thinking-by-default model is not a cheat. Drop without a strike; it registers again
            self.stats["probe_no_answer"] += 1
            self.drop(nid)
            return
        ok = bool(re.search(c["expect"], answer))
        self.store.probe(e["agent"], ok)
        if ok:
            e["strikes"] = 0
            if not e["live"] and self.nodes.get(nid) is e:
                e["live"] = True
                self.sched.nodes.append(node)
            return
        self.stats["probe_failures"] += 1
        e["strikes"] += 1
        if e["strikes"] >= STRIKES or not e["live"]:
            self.store.ban(e["agent"], "failed verification")
            if e["tid"]:
                self.store.ban(e["tid"], f"failed verification (agent {e['agent']})")
                for other, x in list(self.nodes.items()):  # the token's other workers go too
                    if x["tid"] == e["tid"] and other != nid:
                        self.drop(other)
            self.stats["banned"] += 1
            self.drop(nid)

    async def handle_async_request(self, request):
        host = request.url.host
        if not (host.startswith("pull-") and host.endswith(".node")):
            return await self.inner.handle_async_request(request)
        nid = host[len("pull-"):-len(".node")]
        sent = (await request.aread()).decode()
        status, body, ctype = await self.dispatch(nid, request.url.path, sent)
        e = self.nodes.get(nid)
        if status == 200 and e:  # credit the worker for a real job (probe traffic never comes through here)
            try:
                tokens = int(json.loads(body)["usage"]["total_tokens"])
            except (ValueError, KeyError, TypeError):
                tokens = len(body) // 4  # a streamed reply has no usage block: estimate from its size
            tokens = min(tokens, (len(sent) + len(body)) // 2)  # a volunteer cannot claim more than the text could hold
            try:
                model = json.loads(sent).get("model")
            except (ValueError, AttributeError):
                model = None
            rate = self.rates.get(model, self.rates.get("default", 1.0))
            self.store.credit(e["agent"], tokens, milli=round(tokens * rate))  # rate per 1,000 tokens = milli-credits per token
        if random.random() < self.canary_rate and nid in self.nodes:  # spot-check the node that just served real traffic
            asyncio.get_running_loop().create_task(self.probe(nid))
        return httpx.Response(status, content=body.encode(), headers={"content-type": ctype})


def add_routes(app, hub):
    @app.post("/node/register")
    async def register(x_node_token: str = Header(None), x_node_agent: str = Header(None)):
        hub.sweep()
        return {"node_id": hub.register(x_node_token, x_node_agent), "poll_s": hub.poll_s}

    @app.post("/node/link-code")
    async def link_code(x_node_token: str = Header(None), x_node_agent: str = Header(None)):
        return hub.link_code(x_node_token, x_node_agent)

    @app.post("/node/leave")
    async def leave(node_id: str, x_node_token: str = Header(None)):
        """The agent is pausing (its owner is using the machine): drop it now, so jobs queued for it fail over at once
        instead of waiting out the job timeout."""
        hub.entry(node_id, x_node_token)
        hub.drop(node_id)
        return {"ok": True}

    @app.post("/node/telemetry")
    async def telemetry(req: Request, x_node_token: str = Header(None), x_node_agent: str = Header(None)):
        """Opt-in: the agent reports its hardware and idle GPU load for the leaderboard (agent --telemetry)."""
        hub.check(x_node_token, x_node_agent)  # before reading the body
        raw = await req.body()
        if len(raw) > 16_000:
            raise HTTPException(413, "report too large")
        try:
            data = clean_telemetry(json.loads(raw))
        except ValueError:
            raise HTTPException(400, "bad report")
        stored, problem = hub.report(x_node_token, x_node_agent, data)
        return {"ok": True, "stored": stored, "name_rejected": problem or None}

    @app.delete("/node/telemetry")
    async def telemetry_off(x_node_token: str = Header(None), x_node_agent: str = Header(None)):
        """Opt out: remove this machine from the leaderboard and delete what it reported."""
        hub.check(x_node_token, x_node_agent)
        hub.store.forget_telemetry(x_node_agent)
        return {"ok": True}

    @app.get("/node/poll")
    async def poll(node_id: str, x_node_token: str = Header(None)):
        job = await hub.poll(node_id, x_node_token)
        return JSONResponse(job) if job else Response(status_code=204)

    @app.post("/node/result")
    async def result(req: Request, x_node_token: str = Header(None)):
        raw = await req.body()
        if len(raw) > MAX_RESULT:
            raise HTTPException(413, "result too large")
        try:
            d = json.loads(raw)
            args = (str(d["node_id"]), x_node_token, str(d["job"]), int(d["status"]), str(d["body"]),
                    str(d.get("content_type") or "application/json"))
        except Exception:
            raise HTTPException(400, "bad result")
        hub.finish(*args)
        return {"ok": True}
