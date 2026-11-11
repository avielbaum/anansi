"""Volunteer node agent: connects OUT to an Anansi gateway, polls for jobs and runs them on a local
OpenAI-compatible server (Ollama, llama-server, vLLM). No inbound port, so it works behind home NAT.
Run: python node/agent.py --gateway https://gw.example --token TOKEN --local http://127.0.0.1:11434 [--slots 2]
Each slot registers as its own worker. It only ever forwards /v1/chat/completions to the local server.
shortcut: the token is a shared secret per pool, not a per-user Steam-bound certificate (DESIGN.md section 9)."""
import argparse
import asyncio

import httpx

ALLOWED = "/v1/chat/completions"


async def worker(gw, local, token, log=print):
    H, nid, backoff = {"X-Node-Token": token}, None, 1
    while True:
        try:
            if nid is None:
                r = await gw.post("/node/register", headers=H)
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
                    lr = await local.post(ALLOWED, content=job["body"], headers={"content-type": "application/json"},
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


async def serve(gw, local, token, slots=1, log=print):
    await asyncio.gather(*[worker(gw, local, token, log) for _ in range(slots)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--local", default="http://127.0.0.1:11434")
    ap.add_argument("--slots", type=int, default=1)
    a = ap.parse_args()

    async def main():
        async with httpx.AsyncClient(base_url=a.gateway) as gw, httpx.AsyncClient(base_url=a.local) as local:
            await serve(gw, local, a.token, a.slots)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
