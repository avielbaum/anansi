"""Pull nodes: volunteer machines behind NAT connect OUT to the gateway and poll for work (DESIGN.md section 3).
To the scheduler each registered worker is an ordinary Node at http://pull-<id>.node; this transport turns the
gateway's request to that address into a job a polling agent picks up, so routing, failover, ejection and the
retry budget all work unchanged.
shortcut: in memory, one gateway only; a streamed request is answered whole by the agent (the SSE text is relayed
after the node finishes), so streaming from a pull node is correct but not incremental."""
import asyncio
import hmac
import secrets
import time

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .scheduler import Node


class PullHub(httpx.AsyncBaseTransport):
    def __init__(self, sched, tokens, inner, poll_s=20, ttl_s=None, job_timeout_s=60):
        self.sched, self.tokens, self.inner = sched, tokens, inner
        self.poll_s, self.job_timeout_s = poll_s, job_timeout_s
        self.ttl_s = ttl_s if ttl_s is not None else poll_s + 15  # must outlast one long poll
        self.nodes = {}  # id -> {"node", "token", "q", "seen"}
        self.jobs = {}   # job id -> (node id, Future)

    def register(self, token):
        cfg = next((c for t, c in self.tokens.items() if hmac.compare_digest(t.encode(), (token or "").encode())), None)
        if cfg is None:
            raise HTTPException(401, "bad node token")
        nid = secrets.token_hex(6)
        node = Node(f"http://pull-{nid}.node", cfg["models"], cfg.get("region", "volunteer"),
                    cfg.get("upstream_model"), cfg.get("extra"))
        self.sched.nodes.append(node)
        self.nodes[nid] = {"node": node, "token": token, "q": asyncio.Queue(), "seen": time.monotonic()}
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

    async def handle_async_request(self, request):
        host = request.url.host
        if not (host.startswith("pull-") and host.endswith(".node")):
            return await self.inner.handle_async_request(request)
        nid = host[len("pull-"):-len(".node")]
        e = self.nodes.get(nid)
        if e is None:
            raise httpx.ConnectError("node gone")
        jid = secrets.token_hex(8)
        fut = asyncio.get_running_loop().create_future()
        self.jobs[jid] = (nid, fut)
        e["q"].put_nowait({"job": jid, "path": request.url.path, "body": (await request.aread()).decode()})
        try:
            status, body, ctype = await asyncio.wait_for(fut, self.job_timeout_s)
        except asyncio.TimeoutError:
            raise httpx.ReadTimeout("node timed out")
        finally:
            self.jobs.pop(jid, None)
        return httpx.Response(status, content=body.encode(), headers={"content-type": ctype})


def add_routes(app, hub):
    @app.post("/node/register")
    async def register(x_node_token: str = Header(None)):
        hub.sweep()
        return {"node_id": hub.register(x_node_token), "poll_s": hub.poll_s}

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
