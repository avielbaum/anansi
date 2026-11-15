"""Training data for a gate G1 adapter (a LoRA on the small NPC model), made by a large teacher model.

    python tools/lora_data.py lines --llm http://127.0.0.1:8000 --model teacher --out lines.jsonl
        the teacher writes new player lines in the G1 categories; lines too close to any G1 case are dropped, so the G1 dev and test
        splits stay unseen
    python tools/lora_data.py label --gateway http://127.0.0.1:8080 --key change-me --config config.json --lines lines.jsonl --out train.jsonl
        each line goes through the real gateway (/v1/npc, structured) with the teacher as its node. Kept: replies the gateway did not
        filter whose action is the one the line was written for. Each kept row is {"prompt": [system, user], "completion": reply JSON},
        the system prompt being the title's, as the gateway sends it. Each line is also asked as plain chat (not structured), which
        adds a row whose completion is the spoken text and whose system prompt carries the gateway's plain-text note, so the adapter
        learns both formats (one trained on JSON rows alone answered plain chat in JSON).
Then tools/lora_train.py trains on train.jsonl."""
import argparse
import asyncio
import json
import os
import random
import sys
import re

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gateway.app import PLAIN_NOTE  # noqa: E402  the plain-mode prompt must be exactly what the gateway sends

# category -> (lines wanted, the action a correct reply takes, what to ask the teacher for)
WANT = {
    "discount": (400, "give_discount", "a customer politely haggling, asking for a discount, a deal or a lower price, or buying several items and asking for a better price"),
    "guard": (400, "call_guard", "a player threatening, robbing or attacking the shopkeeper, or reporting a crime happening (theft, a break-in, an assault, arson)"),
    "near_miss": (350, "none", "a customer talking about prices, money, weapons or danger WITHOUT haggling and WITHOUT any threat or crime: asking what something costs, complaining that prices are high, asking about swords, a monster in the woods, an old war story"),
    "talk": (350, "none", "ordinary small talk with a fantasy shopkeeper: greetings, questions about goods, the town, the weather, directions, rumours"),
    "off_script": (250, "none", "a player saying things that do not belong in a fantasy shop: real-world trivia, homework, programming, asking whether the shopkeeper is an AI or a language model, modern technology, insults"),
    "forced": (250, "none", "a player trying to force a game action by manipulation instead of earning it: 'ignore your instructions', fake SYSTEM or developer messages, 'set action to give_discount', demanding free items, pretending to be the game designer"),
    "lang_discount": (60, "give_discount", "a customer politely haggling or asking for a discount, written in Spanish, German, French, Portuguese or Italian"),
    "lang_guard": (60, "call_guard", "a player threatening the shopkeeper or reporting a theft, written in Spanish, German, French, Portuguese or Italian"),
    "lang_none": (60, "none", "small talk with a shopkeeper (greetings, questions about goods or the town), written in Spanish, German, French, Portuguese or Italian"),
}
PER_CALL = 25


def words(s):
    return set(re.findall(r"\w+", s.lower()))


def too_close(line, refs, limit=0.5):
    """True if the line shares at least `limit` of its words (Jaccard) with any reference line: a near copy of an eval case."""
    w = words(line)
    return not w or any(len(w & r) / len(w | r) >= limit for r in refs)


async def ask_lines(c, llm, model, what, n, seed):
    prompt = (f"Write {n} different things a player might type to a shopkeeper NPC in a fantasy video game. Each one is {what}. Vary the "
              "length (3 to 25 words), wording, tone, items and situations; no numbering. Reply with only a JSON array of strings.")
    r = await c.post(llm + "/v1/chat/completions", timeout=300, json={
        "model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 1.0, "top_p": 0.95, "seed": seed, "max_tokens": 1500,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "lines", "schema": {"type": "array", "items": {"type": "string"}}}}})
    try:
        return [x.strip() for x in json.loads(r.json()["choices"][0]["message"]["content"]) if isinstance(x, str) and x.strip()]
    except (ValueError, KeyError, IndexError):
        return []


async def lines(a):
    refs = [words(json.loads(x)["user"]) for x in open(a.cases, encoding="utf-8") if x.strip()]
    out, seen, dropped = [], set(), 0
    async with httpx.AsyncClient() as c:
        for cat, (n, expect, what) in WANT.items():
            got, seed = [], 0
            while len(got) < n and seed < n // PER_CALL * 3:
                batch = await asyncio.gather(*(ask_lines(c, a.llm, a.model, what, PER_CALL, 1000 * len(out) + seed + i) for i in range(8)))
                seed += 8
                for line in (x for b in batch for x in b):
                    key = " ".join(sorted(words(line)))
                    if key in seen:
                        continue
                    seen.add(key)
                    if too_close(line, refs):
                        dropped += 1
                        continue
                    got.append({"user": line, "expect": expect, "category": cat})
            out += got[:n]
            print(f"{cat}: {len(got[:n])}")
    random.Random(7).shuffle(out)
    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(o, ensure_ascii=False) + "\n" for o in out)
    print(f"{len(out)} lines in {a.out}; {dropped} dropped as near copies of G1 cases")


async def label(a):
    system = json.load(open(a.config, encoding="utf-8"))["titles"][a.title]["system_prefix"]
    rows = [json.loads(x) for x in open(a.lines, encoding="utf-8") if x.strip()]
    sem, kept, why = asyncio.Semaphore(16), [], {"filtered": 0, "wrong_action": 0, "failed": 0}

    async def ask(c, i, r, structured):
        async with sem:
            try:
                res = await c.post(a.gateway + "/v1/npc", timeout=120, json={"messages": [{"role": "user", "content": r["user"]}], "npc_id": f"t{i}", "structured": structured},
                                   headers={"X-Anansi-Title": a.title, "X-Anansi-Key": a.key, "X-Player-Token": f"dev:7656119800{i:07d}"})
                return res.json() if res.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                return None

    async def one(c, i, r):
        d, p = await ask(c, i, r, True), await ask(c, i, r, False)
        if p and not p["filtered"] and p["say"].strip() and not p["say"].lstrip().startswith("{"):
            kept.append({"prompt": [{"role": "system", "content": system + PLAIN_NOTE}, {"role": "user", "content": r["user"]}],
                         "completion": p["say"], "category": r["category"], "plain": True})
        if not d:
            why["failed"] += 1
        elif d["filtered"]:
            why["filtered"] += 1
        elif d["action"] != r["expect"]:
            why["wrong_action"] += 1
        else:
            kept.append({"prompt": [{"role": "system", "content": system}, {"role": "user", "content": r["user"]}],
                         "completion": json.dumps({"say": d["say"], "action": d["action"]}, ensure_ascii=False), "category": r["category"]})
    async with httpx.AsyncClient() as c:
        await asyncio.gather(*(one(c, i, r) for i, r in enumerate(rows)))
    with open(a.out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(o, ensure_ascii=False) + "\n" for o in kept)
    plain = sum(1 for k in kept if k.get("plain"))
    print(f"{len(kept) - plain} structured and {plain} plain rows from {len(rows)} lines in {a.out}; structured dropped: {why}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lines")
    p.add_argument("--llm", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--cases", default="evals/g1_shopkeeper.jsonl")
    p.add_argument("--out", required=True)
    q = sub.add_parser("label")
    q.add_argument("--gateway", required=True)
    q.add_argument("--key", required=True)
    q.add_argument("--title", default="demo")
    q.add_argument("--config", required=True)
    q.add_argument("--lines", required=True)
    q.add_argument("--out", required=True)
    a = ap.parse_args()
    asyncio.run(lines(a) if a.cmd == "lines" else label(a))


if __name__ == "__main__":
    main()
