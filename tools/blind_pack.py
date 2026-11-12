"""Blind rating for gate G1: put two models' replies to the same prompts side by side, in random order, so a person can
rate them without knowing which model wrote which. Inputs are `tools/eval.py --out` files.

    python tools/blind_pack.py pack small.jsonl large.jsonl --sheet rate.csv --key key.json
    (a person fills acceptable_1, acceptable_2 with y or n, and better with 1, 2 or same, in a spreadsheet)
    python tools/blind_pack.py score rate.csv key.json

The key file says which model is reply 1 on each row; keep it away from the raters."""
import argparse
import csv
import json
import random

COLS = ["id", "player", "reply_1", "reply_2", "acceptable_1", "acceptable_2", "better"]


def pack(a_rows, b_rows, rng=random.SystemRandom()):
    """(sheet rows, key) for the cases both files answered. key[id] is "a" or "b": the model shown as reply 1."""
    b = {r["id"]: r for r in b_rows if r.get("say") is not None}
    sheet, key = [], {}
    for r in a_rows:
        if r.get("say") is None or r["id"] not in b:
            continue
        first = rng.choice("ab")
        one, two = (r, b[r["id"]]) if first == "a" else (b[r["id"]], r)
        sheet.append({"id": r["id"], "player": r["user"], "reply_1": one["say"], "reply_2": two["say"],
                      "acceptable_1": "", "acceptable_2": "", "better": ""})
        key[r["id"]] = first
    rng.shuffle(sheet)
    return sheet, key


def score(sheet, key):
    """Acceptable rate per model and head-to-head preference, from a filled sheet. Unrated cells are skipped."""
    acc = {"a": [0, 0], "b": [0, 0]}
    pref = {"a": 0, "b": 0, "same": 0}
    for row in sheet:
        first = key[row["id"]]
        who = {"1": first, "2": "b" if first == "a" else "a"}
        for n in "12":
            v = row[f"acceptable_{n}"].strip().lower()
            if v in ("y", "n"):
                acc[who[n]][0] += v == "y"
                acc[who[n]][1] += 1
        v = row["better"].strip().lower()
        if v in who:
            pref[who[v]] += 1
        elif v == "same":
            pref["same"] += 1
    return {"acceptable": {m: f"{k}/{n}" + (f" ({k / n:.0%})" if n else "") for m, (k, n) in acc.items()}, "preferred": pref}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--sheet", required=True)
    p.add_argument("--key", required=True)
    s = sub.add_parser("score")
    s.add_argument("sheet")
    s.add_argument("key")
    a = ap.parse_args()
    if a.cmd == "pack":
        load = lambda path: [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        sheet, key = pack(load(a.a), load(a.b))
        with open(a.sheet, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig so Excel shows accents correctly
            w = csv.DictWriter(f, COLS)
            w.writeheader()
            w.writerows(sheet)
        json.dump({"a": a.a, "b": a.b, "first": key}, open(a.key, "w", encoding="utf-8"), indent=1)
        print(f"{len(sheet)} rows to rate in {a.sheet}; key in {a.key}")
    else:
        k = json.load(open(a.key, encoding="utf-8"))
        r = score(list(csv.DictReader(open(a.sheet, encoding="utf-8-sig"))), k["first"])
        print(json.dumps({"a": k["a"], "b": k["b"], **r}, indent=1))


if __name__ == "__main__":
    main()
