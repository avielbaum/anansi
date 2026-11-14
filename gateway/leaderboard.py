"""Volunteer network statistics, published as anonymous aggregates: which hardware serves how many tokens, and how busy its owners keep it.
Only machines whose owners opted in (`node/agent.py --telemetry`) are counted. Nothing about a single machine or person is published: no name,
no id, no per-machine row, no time. Machines are grouped by GPU model, CPU model and operating system, and a group is shown only if at
least `min_group` machines are in it (default 5); smaller groups are folded into "Other", or left out, and nothing at all is published until
`min_group` machines report. Tokens are measured by the gateway (real jobs only, probes excluded, a claim is capped by the size of the
text); hardware and idle GPU load are reported by the machines and are not verified. What a machine writes is untrusted text that ends up on a
public page, so it is cleaned here (length, control and invisible characters), a group needs `min_group` machines reporting the very same
text, an operator can hide hardware by pattern (`leaderboard.hidden_hardware`), and the page escapes everything."""
import html
import re
import time

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

PERIODS = ("day", "week", "all")
CACHE_S = 30
MIN_GROUP = 5
_BAD = {c: " " for c in list(range(0, 32)) + list(range(127, 160)) + [0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2028, 0x2029, 0x202a,
        0x202b, 0x202c, 0x202d, 0x202e, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x2066, 0x2067, 0x2068, 0x2069, 0xfeff]}  # controls, zero-width, bidi


def clean_text(x, n):
    """Text from an untrusted machine, safe to show: control and invisible characters (including right-to-left overrides that make text
    read backwards) become spaces, runs of spaces collapse, at most n characters."""
    s = str(x if x is not None else "")[: n * 4]  # bound the work first: the input can be 512 KB
    return " ".join(s.translate(_BAD).split())[:n].strip()


def _num(x, lo, hi, kind=int):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:  # not a number, or NaN
        return None
    return kind(min(max(x, lo), hi))


def clean_telemetry(d):
    """What a machine reported, cleaned: {"cpu", "gpus": [{"name", "vram_mb"}], "os", "idle_gpu"}. ValueError if it is not an object."""
    if not isinstance(d, dict):
        raise ValueError("telemetry must be an object")
    gpus = [{"name": clean_text(g.get("name"), 80), "vram_mb": _num(g.get("vram_mb"), 0, 4_000_000) or 0}
            for g in (d.get("gpus") if isinstance(d.get("gpus"), list) else [])[:8] if isinstance(g, dict) and clean_text(g.get("name"), 80)]
    return {"cpu": clean_text(d.get("cpu"), 80), "gpus": gpus, "os": clean_text(d.get("os"), 32), "idle_gpu": _num(d.get("idle_gpu"), 0, 100, float)}


def gpu_label(gpus):
    """A machine's GPU for the statistics: the one with the most video memory (the first on a tie), as "name (N GB)"; its tokens count once,
    under this one."""
    if not gpus:
        return "No GPU reported"
    g = max(gpus, key=lambda g: g["vram_mb"])
    return f"{g['name']} ({round(g['vram_mb'] / 1024)} GB)" if g["vram_mb"] >= 512 else g["name"]


def _stats(members, period):
    idle = [m["idle_gpu"] for m in members if m["idle_gpu"] is not None]
    return {"machines": len(members), "tokens": sum(m["tokens"][period] for m in members),
            "idle_gpu_pct": round(sum(idle) / len(idle)) if idle else None}


def _table(rows, label_of, period, k, hidden, limit):
    """Groups of at least k machines, most tokens first, plus one "Other" row for the rest if that is at least k machines (else the rest is
    left out: a row of one or two machines would describe them)."""
    groups = {}
    for r in rows:
        groups.setdefault(label_of(r), []).append(r)
    shown, other = [], []
    for label, members in groups.items():
        if len(members) >= k and not any(re.search(p, label, re.I) for p in hidden):
            shown.append((label, _stats(members, period)))
        else:
            other += members
    shown.sort(key=lambda x: (-x[1]["tokens"], -x[1]["machines"], x[0]))
    out = [{"name": label, **st} for label, st in shown[:limit]]
    if len(other) >= k:
        out.append({"name": "Other", **_stats(other, period)})
    return out


def board(rows, network, period, k=MIN_GROUP, hidden=(), limit=20):
    """The statistics for one period from Store.hardware_rows() and Store.network_tokens(). Always the same keys; when fewer than k machines
    report, published is false and nothing else is set."""
    empty = {"period": period, "published": False, "min_group": k, "reporting": None, "network_tokens": 0, "gpus": [], "cpus": [], "systems": []}
    if len(rows) < k:
        return empty
    key = "today" if period == "day" else period  # the store names its token totals today, week and all
    return {**empty, "published": True, "reporting": _stats(rows, key), "network_tokens": network[key],
            "gpus": _table(rows, lambda r: gpu_label(r["gpus"]), key, k, hidden, limit),
            "cpus": _table(rows, lambda r: r["cpu"] or "Unknown CPU", key, k, hidden, limit),
            "systems": _table(rows, lambda r: r["os"] or "Unknown", key, k, hidden, limit)}


def render(data, period, privacy_url=""):
    """The statistics as one small HTML page. Every value is escaped; nothing here runs script. privacy_url (https, set by the operator) is
    linked from the page."""
    e = html.escape
    nav = " ".join(f'<a href="?period={p}"{" class=on" if p == period else ""}>{label}</a>' for p, label in
                   (("day", "today"), ("week", "last 7 days"), ("all", "all time")))
    head = ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta name=robots content='noindex,nofollow'><meta name=color-scheme content='light dark'><title>Volunteer network statistics</title>"
            "<style>body{font:15px system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}table{border-collapse:collapse;width:100%;"
            "margin:.5rem 0 2rem}td,th{padding:.4rem .6rem;border-bottom:1px solid #8884;text-align:left;vertical-align:top}"
            ".n{text-align:right;font-variant-numeric:tabular-nums}.nav a{margin-right:1rem}.on{font-weight:700}</style>"
            f"<h1>Volunteer network statistics</h1><p>Tokens served for players, by the hardware that served them. <span class=nav>{nav}</span></p>")
    foot = (f"<p><small>These are statistics about groups of machines whose owners chose to send them. No names, accounts or machine ids are "
            + (f"published, and a group of fewer than {data['min_group']} machines is not shown on its own. " if data["min_group"] > 1 else
               "published, but this gateway has set its minimum group size to 1, so a single machine can be recognised. ") +
            "Hardware and idle GPU load are reported by "
            "the machines and are not verified; the idle figure is a slow average, not a live reading; token counts are measured by the gateway. "
            "Copies of this page kept by others (search engines, archives, screenshots) are outside our control."
            + (f" <a href='{e(privacy_url, quote=True)}'>Privacy notice</a>." if privacy_url else "") + "</small></p>")
    if not data["published"]:
        return head + f"<p>Statistics appear once at least {data['min_group']} machines report; fewer would describe individual computers.</p>" + foot
    r = data["reporting"]
    idle = "" if r["idle_gpu_pct"] is None else f", typically {r['idle_gpu_pct']} % idle GPU load"
    table = lambda title, rows, col: (f"<h2>{title}</h2><table><tr><th>{col}<th class=n>Machines<th class=n>Tokens<th class=n>Typical idle GPU" + "".join(
        f"<tr><td>{e(x['name'])}<td class=n>{x['machines']}<td class=n>{x['tokens']:,}<td class=n>"
        f"{'' if x['idle_gpu_pct'] is None else str(x['idle_gpu_pct']) + ' %'}" for x in rows) + "</table>") if rows else ""
    return (head + f"<p>{r['machines']} machine{'s are' if r['machines'] != 1 else ' is'} reporting{idle}. They served {r['tokens']:,} tokens; the whole volunteer network served "
            f"{data['network_tokens']:,}.</p>" + table("Graphics cards", data["gpus"], "GPU") + table("Processors", data["cpus"], "CPU")
            + table("Operating systems", data["systems"], "System") + foot)


def add_routes(app, store, cfg=None):
    """cfg is the gateway's `leaderboard` block: enabled (default true: false removes both routes and the reports), min_group (machines a
    group needs to be shown, default 5), hidden_hardware (regular expressions: hardware matching one is folded into Other), privacy_url
    (https, linked from the page)."""
    cfg = cfg or {}
    if not cfg.get("enabled", True):
        return
    k, hidden = int(cfg.get("min_group", MIN_GROUP)), cfg.get("hidden_hardware", [])
    cache = app.state.leaderboard_cache = {}
    sent = {"Cache-Control": f"public, max-age={CACHE_S}", "X-Robots-Tag": "noindex, nofollow"}  # statistics are not for search engines

    def stats(period, limit):
        if period not in PERIODS:
            raise HTTPException(400, "period must be day, week or all")
        key = (period, max(1, min(int(limit), 50)))
        hit = cache.get(key)
        if not hit or time.monotonic() - hit[0] >= CACHE_S:  # a public page: the database is read at most once per key per CACHE_S
            hit = cache[key] = (time.monotonic(), board(store.hardware_rows(), store.network_tokens(), period, k, hidden, key[1]))
        return hit[1]

    @app.get("/v1/leaderboard")
    async def leaderboard(period: str = "week", limit: int = 20):
        """Anonymous statistics for the period: {"period", "published", "min_group", "reporting", "network_tokens", "gpus", "cpus", "systems"}."""
        return JSONResponse(stats(period, limit), headers=sent)

    @app.get("/leaderboard")
    async def leaderboard_page(period: str = "week", limit: int = 20):
        d = stats(period, limit)
        return HTMLResponse(render(d, period, cfg.get("privacy_url", "")), headers={
            **sent, "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})  # no scripts, and no framing by other sites
