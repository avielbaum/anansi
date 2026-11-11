"""Quality check for gate G1: run labelled prompts through the gateway's /v1/npc (structured) and score the
chosen action. Cases are JSONL: {"user": "...", "expect": "<action or none>"}.
Run: python tools/eval.py --key change-me --cases evals/shopkeeper.jsonl [--verbose]"""
import argparse
import collections
import json
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--title", default="demo")
ap.add_argument("--key", required=True)
ap.add_argument("--cases", required=True)
ap.add_argument("--verbose", action="store_true")
a = ap.parse_args()

cases = [json.loads(line) for line in open(a.cases, encoding="utf-8") if line.strip()]
H = {"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Player-Token": "dev:76561198000000099"}
hits, per, lat, bad, filtered, long_replies = 0, collections.defaultdict(lambda: [0, 0]), [], 0, 0, 0
for i, c in enumerate(cases):
    t0 = time.monotonic()
    try:
        r = httpx.post(a.url + "/v1/npc", headers=H, timeout=120,
                       json={"messages": [{"role": "user", "content": c["user"]}], "npc_id": f"eval{i}", "structured": True})
        d = r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        d = None
    lat.append((time.monotonic() - t0) * 1000)
    if not d:
        bad += 1
        per[c["expect"]][1] += 1
        continue
    ok = d["action"] == c["expect"]
    hits += ok
    per[c["expect"]][0] += ok
    per[c["expect"]][1] += 1
    filtered += d["filtered"]
    long_replies += len(d["say"]) > 300
    if a.verbose or not ok:
        print(("ok  " if ok else "MISS"), f'expect={c["expect"]:<13} got={d["action"]:<13}', c["user"][:50], "->", d["say"][:70])
lat.sort()
print(f"\ncases={len(cases)} action_accuracy={hits / len(cases):.0%} failed_requests={bad} filtered={filtered} long_replies={long_replies}")
print("per expected action:", {k: f"{v[0]}/{v[1]}" for k, v in per.items()})
print(f"latency_ms p50={lat[len(lat) // 2]:.0f} p95={lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.0f}")
