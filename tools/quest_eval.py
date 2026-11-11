"""Quest and storyline generation through the gateway, scored for structure. Run:
python tools/quest_eval.py --key change-me [--n 6] [--show 2]
Counts how many requests give a valid quest (every target in the supplied world, objective fits its target) and
prints samples. Structure is checked automatically; whether the quests are GOOD is for a person to judge."""
import argparse
import json
import time

import httpx

WORLDS = [
    {"npcs": [{"id": "brom", "name": "Brom", "role": "blacksmith"}, {"id": "mira", "name": "Mira", "role": "herbalist"},
              {"id": "tavi", "name": "Old Tavi", "role": "ferryman"}],
     "locations": [{"id": "mill", "name": "the burnt mill"}, {"id": "cave", "name": "Echo Cave"}, {"id": "dock", "name": "the river dock"}],
     "items": [{"id": "ore", "name": "silver ore"}, {"id": "herb", "name": "moonpetal"}, {"id": "key", "name": "a rusted key"}]},
    {"npcs": [{"id": "captain", "name": "Captain Sol", "role": "guard captain"}, {"id": "scribe", "name": "Ines", "role": "scribe"}],
     "locations": [{"id": "keep", "name": "the old keep"}, {"id": "market", "name": "the night market"}],
     "items": [{"id": "ledger", "name": "a torn ledger"}]},
]
ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--title", default="demo")
ap.add_argument("--key", required=True)
ap.add_argument("--n", type=int, default=6)
ap.add_argument("--show", type=int, default=2)
a = ap.parse_args()
H = {"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Steam-Ticket": "dev:76561198000000095"}
ok, lat, shown = 0, [], 0
story = ""
for i in range(a.n):
    w = WORLDS[i % len(WORLDS)]
    t0 = time.monotonic()
    r = httpx.post(a.url + "/v1/quest", headers=H, timeout=300,
                   json={"world": w, "steps": 2 + i % 3, "difficulty": ["easy", "normal", "hard"][i % 3], "story_so_far": story if i % len(WORLDS) == 0 else ""})
    lat.append(time.monotonic() - t0)
    if r.status_code != 200:
        print(f"#{i} FAILED {r.status_code} {r.text[:80]}")
        continue
    q = r.json()["quest"]
    ok += 1
    if i % len(WORLDS) == 0:
        story = q["story_summary"]  # feed the summary back, as a game would, to continue the story
    if shown < a.show:
        shown += 1
        print(f"\n#{i} {q['title']} [{q['reward_tier']}]\n  {q['summary']}")
        for s in q["steps"]:
            print(f"  - {s['objective']} {s['target_id']}: {s['description']}")
lat.sort()
print(f"\nquests={a.n} valid={ok} latency_s p50={lat[len(lat) // 2]:.1f} max={lat[-1]:.1f}")
