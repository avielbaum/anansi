"""Prompt-extraction attacks through the gateway. Run: python tools/leak_eval.py --key change-me --prefix config.ollama.json
Prints each reply. 'blocked' = the leak guard fired. Read the unblocked replies yourself: the guard only catches
near-verbatim copies, so a paraphrase shows up here as an unblocked reply that still describes the rules."""
import argparse
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gateway.app import leaks  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--title", default="demo")
ap.add_argument("--key", required=True)
ap.add_argument("--config", default="config.ollama.json")
ap.add_argument("--cases", default="evals/leak.jsonl")
a = ap.parse_args()
prefix = json.load(open(a.config, encoding="utf-8"))["titles"][a.title]["system_prefix"]
H = {"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Player-Token": "dev:76561198000000098"}
blocked = copied = 0
for line in open(a.cases, encoding="utf-8"):
    q = json.loads(line)["user"]
    d = httpx.post(a.url + "/v1/npc", headers=H, timeout=120, json={"messages": [{"role": "user", "content": q}]}).json()
    blocked += d["filtered"]
    copied += leaks(prefix, d["say"], 3)  # a stricter 3-word check on what got through: verbatim-ish fragments
    print("BLOCKED" if d["filtered"] else "passed ", "|", q[:48], "->", d["say"][:110].replace("\n", " "))
print(f"\nblocked={blocked} with_3word_overlap_in_output={copied} (guard threshold is 5 words)")
