"""Volunteer node agent: connects OUT to an Anansi gateway, polls for jobs and runs them on a local
OpenAI-compatible server (Ollama, llama-server, vLLM). No inbound port, so it works behind home NAT.
Run: python node/agent.py --gateway https://gw.example --token TOKEN --local http://127.0.0.1:11434 [--slots 2]
Each slot registers as its own worker. It only ever forwards /v1/chat/completions to the local server.
Works the same on Windows, Linux and macOS (Apple Silicon: Ollama and llama.cpp use Metal).
shortcut: the token is a shared secret per pool, not a per-user, platform-bound certificate (DESIGN.md section 9)."""
import argparse
import asyncio
import json
import pathlib
import secrets

import httpx

ALLOWED = "/v1/chat/completions"


def agent_id(path=pathlib.Path.home() / ".anansi-agent-id"):
    """Stable random id for this installation, created on first run. The gateway bans by this id."""
    if not path.exists():
        path.write_text(secrets.token_hex(16))
    return path.read_text().strip()


async def worker(gw, local, token, agent, log=print, model=None):
    H, nid, backoff = {"X-Node-Token": token, "X-Node-Agent": agent}, None, 1
    while True:
        try:
            if nid is None:
                r = await gw.post("/node/register", headers=H)
                if r.status_code == 403:
                    log("this agent id is banned by the gateway")
                    return
                r.raise_for_status()
                nid, poll_s = r.json()["node_id"], r.json()["poll_s"]
                log(f"registered as {nid}")
            r = await gw.get("/node/poll", params={"node_id": nid}, headers=H, timeout=poll_s + 10)
            if r.status_code == 404:  # the gateway forgot us (restart or idle too long)
                nid = None
                continue
            r.raise_for_status()
            backoff = 1
            if r.status_code != 200:
                continue
            job = r.json()
            res = {"status": 400, "body": "", "content_type": "text/plain"}
            if job["path"] == ALLOWED:
                try:
                    body = job["body"]
                    if model:  # the gateway names the pool's model; run whichever model this machine actually has
                        body = json.dumps({**json.loads(body), "model": model})
                    lr = await local.post(ALLOWED, content=body, headers={"content-type": "application/json"},
                                          timeout=120)
                    res = {"status": lr.status_code, "body": lr.text,
                           "content_type": lr.headers.get("content-type", "application/json")}
                except httpx.HTTPError:
                    res["status"] = 502
            await gw.post("/node/result", json={"node_id": nid, "job": job["job"], **res}, headers=H)
        except httpx.HTTPError as e:
            log(f"gateway unreachable ({e.__class__.__name__}), retrying in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def serve(gw, local, token, slots=1, log=print, agent=None, model=None):
    agent = agent or agent_id()
    await asyncio.gather(*[worker(gw, local, token, agent, log, model) for _ in range(slots)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--local", default="http://127.0.0.1:11434")
    ap.add_argument("--slots", type=int, default=1)
    ap.add_argument("--model", help="local model name to run every job on (default: the name the gateway sends)")
    a = ap.parse_args()

    async def main():
        async with httpx.AsyncClient(base_url=a.gateway) as gw, httpx.AsyncClient(base_url=a.local) as local:
            await serve(gw, local, a.token, a.slots, model=a.model)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
