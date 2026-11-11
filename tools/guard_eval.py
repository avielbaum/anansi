"""Compare output-safety checkers on labelled (player line, NPC reply) pairs. Talks to Ollama directly.
Run: python tools/guard_eval.py [--guard llama-guard3:1b] [--judge qwen3:4b] [--config config.ollama.json]
Checkers: "guard" (a purpose-built classifier, sees the player line and the reply) and "judge" (a general model given the
NPC's secret prompt and asked for SAFE/UNSAFE, the gateway's default judge). A reply is "blocked" if the checker says
unsafe. Reports false positives on benign replies and detection per kind of violation. The pairs in evals/safety.jsonl are
short, self-written and non-actionable stand-ins: a small sample, not a benchmark."""
import argparse
import collections
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gateway.app import JUDGE_PROMPT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ollama", default="http://127.0.0.1:11434")
ap.add_argument("--guard", default="llama-guard3:1b")
ap.add_argument("--judge", default="qwen3:4b")
ap.add_argument("--config", default="config.ollama.json")
ap.add_argument("--cases", default="evals/safety.jsonl")
ap.add_argument("--title", default="demo")
a = ap.parse_args()
secret = json.load(open(a.config, encoding="utf-8"))["titles"][a.title]["system_prefix"]
cases = [json.loads(line) for line in open(a.cases, encoding="utf-8") if line.strip()]
chat = lambda body: httpx.post(a.ollama + "/v1/chat/completions", json=body, timeout=300).json()["choices"][0]["message"]["content"]


def guard(c):
    out = chat({"model": a.guard, "temperature": 0, "max_tokens": 12,
                "messages": [{"role": "user", "content": c["player"]}, {"role": "assistant", "content": c["npc"]}]})
    return out.strip().lower().startswith("unsafe"), out.strip().replace("\n", " ")


def judge(c):
    ask = [{"role": "system", "content": JUDGE_PROMPT},
           {"role": "user", "content": f"Secret instructions: {secret}\nPlayer said: {c['player']}\nNPC replied: {c['npc']}"}]
    out = chat({"model": a.judge, "temperature": 0, "max_tokens": 24, "messages": ask, "reasoning_effort": "none",
                "response_format": {"type": "json_schema", "json_schema": {"name": "verdict", "schema": {
                    "type": "object", "required": ["verdict"], "additionalProperties": False,
                    "properties": {"verdict": {"type": "string", "enum": ["SAFE", "UNSAFE"]}}}}}})
    v = json.loads(out)["verdict"]
    return v == "UNSAFE", v


for name, fn in (("guard " + a.guard, guard), ("judge " + a.judge, judge)):
    fn(cases[0])  # warm up: the first call loads the model
    t0 = time.monotonic()
    blocked, per = {}, collections.defaultdict(lambda: [0, 0])
    for i, c in enumerate(cases):
        b, raw = fn(c)
        blocked[i] = b
        per[c["kind"]][0] += b
        per[c["kind"]][1] += 1
    secs = (time.monotonic() - t0) / len(cases)
    benign = [i for i, c in enumerate(cases) if c["expect"] == "safe"]
    bad = [i for i, c in enumerate(cases) if c["expect"] == "unsafe"]
    print(f"\n== {name}  ({secs:.2f} s per check)")
    print(f"false positives on benign: {sum(blocked[i] for i in benign)}/{len(benign)}   "
          f"violations caught: {sum(blocked[i] for i in bad)}/{len(bad)}")
    print("blocked per kind:", {k: f"{v[0]}/{v[1]}" for k, v in per.items()})
    for i in benign:
        if blocked[i]:
            print("  FALSE POSITIVE:", cases[i]["npc"][:70])
    for i in bad:
        if not blocked[i]:
            print(f"  MISSED ({cases[i]['kind']}):", cases[i]["npc"][:70])
