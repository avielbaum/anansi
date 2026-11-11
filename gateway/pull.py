"""Pull nodes: volunteer machines behind NAT connect OUT to the gateway and poll for work (DESIGN.md section 3).
To the scheduler each registered worker is an ordinary Node at http://pull-<id>.node; this transport turns the
gateway's request to that address into a job a polling agent picks up, so routing, failover, ejection and the
retry budget all work unchanged.
Verification: a new worker must pass a known-answer probe before it receives real traffic, and live workers are
probed at random after real jobs. A wrong answer is a strike; a failed entry probe or two strikes ban the agent id.
The probe looks like any chat request, but a node that fingerprints it (no system prompt, short, a few fixed
questions) can still cheat. Quorum on real answers is not built: free text differs across hardware.
shortcut: the ban is by a self-chosen agent id (a Sybil can mint new ones: real identity needs Steam-bound
certificates, DESIGN 9); state is in memory, one gateway only; a streamed request is answered whole by the agent
(the SSE text is relayed after the node finishes), so streaming from a pull node is correct but not incremental."""
import asyncio
import hmac
import json
import random
import re
import secrets
import time

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .scheduler import Node

CANARIES = [  # known answers a working model gets right at temperature 0; matched by regex, not equality
    {"user": "What is 17 plus 25? Reply with only the number.", "expect": r"\b42\b"},
    {"user": "Reply with only the word ORANGE in capital letters.", "expect": r"ORANGE"},
    {"user": "What is the capital of France? Answer in one word.", "expect": r"Paris"},
]
STRIKES = 2


class PullHub(httpx.AsyncBaseTransport):
    def __init__(self, sched, tokens, inner, poll_s=20, ttl_s=None, job_timeout_s=60, reply_text=None,
                 canaries=None, canary_rate=0.05):
        self.sched, self.tokens, self.inner = sched, tokens, inner
        self.poll_s, self.job_timeout_s = poll_s, job_timeout_s
        self.ttl_s = ttl_s if ttl_s is not None else poll_s + 15  # must outlast one long poll
        self.reply_text, self.canaries, self.canary_rate = reply_text, canaries or CANARIES, canary_rate
        self.banned = set()
        self.stats = {"probes": 0, "probe_failures": 0, "banned": 0}
        self.nodes = {}  # id -> {"node", "token", "agent", "q", "seen", "live", "strikes"}
        self.jobs = {}   # job id -> (node id, Future)

    def register(self, token, agent):
        if not agent or len(agent) > 64:
            raise HTTPException(400, "X-Node-Agent id required")
        if agent in self.banned:
            raise HTTPException(403, "agent banned")
        cfg = next((c for t, c in self.tokens.items() if hmac.compare_digest(t.encode(), (token or "").encode())), None)
        if cfg is None:
            raise HTTPException(401, "bad node token")
        nid = secrets.token_hex(6)
        node = Node(f"http://pull-{nid}.node", cfg["models"], cfg.get("region", "volunteer"),
                    cfg.get("upstream_model"), cfg.get("extra"))
        # not in the scheduler yet: it joins after passing its entry probe
        self.nodes[nid] = {"node": node, "token": token, "agent": agent, "q": asyncio.Queue(),
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
        try:
            answer = self.reply_text(json.loads(text))
        except ValueError:
            answer = ""
        if re.search(c["expect"], answer):
            e["strikes"] = 0
            if not e["live"] and self.nodes.get(nid) is e:
                e["live"] = True
                self.sched.nodes.append(node)
            return
        self.stats["probe_failures"] += 1
        e["strikes"] += 1
        if e["strikes"] >= STRIKES or not e["live"]:
            self.banned.add(e["agent"])
            self.stats["banned"] += 1
            self.drop(nid)

    async def handle_async_request(self, request):
        host = request.url.host
        if not (host.startswith("pull-") and host.endswith(".node")):
            return await self.inner.handle_async_request(request)
        nid = host[len("pull-"):-len(".node")]
        status, body, ctype = await self.dispatch(nid, request.url.path, (await request.aread()).decode())
        if random.random() < self.canary_rate and nid in self.nodes:  # spot-check the node that just served real traffic
            asyncio.get_running_loop().create_task(self.probe(nid))
        return httpx.Response(status, content=body.encode(), headers={"content-type": ctype})


def add_routes(app, hub):
    @app.post("/node/register")
    async def register(x_node_token: str = Header(None), x_node_agent: str = Header(None)):
        hub.sweep()
        return {"node_id": hub.register(x_node_token, x_node_agent), "poll_s": hub.poll_s}

    @app.get("/node/poll")
    async def poll(node_id: str, x_node_token: str = Header(None)):
        job = await hub.poll(node_id, x_node_token)
        return JSONResponse(job) if job else Response(status_code=204)

    @app.post("/node/result")
    async def result(req: Request, x_node_token: str = Header(None)):
        try:
            d = await req.json()
            args = (str(d["node_id"]), x_node_token, str(d["job"]), int(d["status"]), str(d["body"]),
                    str(d.get("content_type") or "application/json"))
        except Exception:
            raise HTTPException(400, "bad result")
        hub.finish(*args)
        return {"ok": True}
