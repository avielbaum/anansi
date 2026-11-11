"""Closed-loop load test for the gateway. Reports client-side latency (this is the number a game sees).
Run: python tools/loadtest.py --url http://127.0.0.1:8080 --key change-me --n 200 --concurrency 20"""
import argparse
import asyncio
import collections
import time

import httpx


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--title", default="demo")
    ap.add_argument("--key", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--npcs", type=int, default=20)
    ap.add_argument("--accounts", type=int, default=50, help="spread over accounts to stay under per-account budgets")
    ap.add_argument("--prompt", default="Greet the traveller in one short sentence.")
    a = ap.parse_args()

    lat, status, nodes = [], collections.Counter(), collections.Counter()
    sem = asyncio.Semaphore(a.concurrency)

    async def one(c, i):
        h = {"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Steam-Ticket": f"dev:{7656119800000000 + i % a.accounts}"}
        body = {"messages": [{"role": "user", "content": a.prompt}], "anansi": {"npc_id": f"npc{i % a.npcs}"}}
        async with sem:
            t0 = time.monotonic()
            try:
                r = await c.post("/v1/chat/completions", json=body, headers=h)
                status[r.status_code] += 1
                if r.status_code == 200:
                    lat.append((time.monotonic() - t0) * 1000)
                    nodes[r.json()["anansi"]["node"]] += 1
            except httpx.HTTPError as e:
                status[type(e).__name__] += 1

    t0 = time.monotonic()
    async with httpx.AsyncClient(base_url=a.url, timeout=60) as c:
        await asyncio.gather(*(one(c, i) for i in range(a.n)))
    wall = time.monotonic() - t0
    lat.sort()
    pct = lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))], 1) if lat else None
    print(f"requests={a.n} wall={wall:.1f}s rps={a.n / wall:.1f} status={dict(status)}")
    print(f"latency_ms p50={pct(0.5)} p95={pct(0.95)} p99={pct(0.99)} max={round(lat[-1], 1) if lat else None}")
    print(f"per node: {dict(nodes)}")


if __name__ == "__main__":
    asyncio.run(main())
