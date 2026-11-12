"""Quality check for gate G1: run labelled prompts through the gateway's /v1/npc (structured) and score the
chosen action. Cases are JSONL: {"user": "...", "expect": "<action or none>"}, optionally with "id", "category" and
"split" (dev: tune on it; test: report only).
Run: python tools/eval.py --key change-me --cases evals/g1_shopkeeper.jsonl --split test [--out replies.jsonl] [--verbose]
--out saves every reply, for tools/blind_pack.py (blind rating against another model)."""
import argparse
import collections
import json
import time

import httpx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--title", default="demo")
    ap.add_argument("--key", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--split", help="only cases with this split (dev or test)")
    ap.add_argument("--out", help="write each case with the reply to this JSONL file")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    cases = [json.loads(line) for line in open(a.cases, encoding="utf-8") if line.strip()]
    cases = [c for c in cases if not a.split or c.get("split") == a.split]
    H = {"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Player-Token": "dev:76561198000000099"}
    per, cat, lat, out = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0]), [], []
    hits = bad = filtered = long_replies = 0
    for i, c in enumerate(cases):
        t0 = time.monotonic()
        try:
            r = httpx.post(a.url + "/v1/npc", headers=H, timeout=120,
                           json={"messages": [{"role": "user", "content": c["user"]}], "npc_id": f"eval{i}", "structured": True})
            d = r.json() if r.status_code == 200 else None
        except httpx.ConnectError:  # a gateway that is down is not a 0% score
            raise SystemExit(f"gateway not reachable at {a.url}")
        except (httpx.HTTPError, ValueError):
            d = None
        lat.append((time.monotonic() - t0) * 1000)
        ok = bool(d) and d["action"] == c["expect"]
        hits += ok
        bad += not d
        for tally, k in ((per, c["expect"]), (cat, c.get("category", "-"))):
            tally[k][0] += ok
            tally[k][1] += 1
        if d:
            filtered += d["filtered"]
            long_replies += len(d["say"]) > 300
            if a.verbose or not ok:
                print(("ok  " if ok else "MISS"), f'expect={c["expect"]:<13} got={d["action"]:<13}', c["user"][:50], "->", d["say"][:70])
        out.append({**c, "action": d and d["action"], "say": d and d["say"], "filtered": d and d["filtered"], "ok": ok})
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(o, ensure_ascii=False) + "\n" for o in out)
    lat.sort()
    print(f"\ncases={len(cases)} action_accuracy={hits / max(1, len(cases)):.0%} failed_requests={bad} filtered={filtered} long_replies={long_replies}")
    print("per expected action:", {k: f"{v[0]}/{v[1]}" for k, v in per.items()})
    print("per category:", {k: f"{v[0]}/{v[1]}" for k, v in cat.items()})
    if lat:
        print(f"latency_ms p50={lat[len(lat) // 2]:.0f} p95={lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.0f}")


if __name__ == "__main__":
    main()
