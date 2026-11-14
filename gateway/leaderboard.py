"""Volunteer leaderboard: total tokens processed per machine and per player, with the hardware each machine reports.
Nothing is public unless its owner opted in: a machine appears only if its agent was started with --telemetry, and a player only
once they chose a display name (POST /v1/credits/name). Tokens come from the gateway's own ledger (real jobs only, probes excluded,
capped by the size of the text), so they cannot be inflated; hardware and idle GPU load are reported by the machine and are shown as
reported. Everything an outside machine or player writes is untrusted and is shown to other people, so it is cleaned here
(length, control and invisible characters) and escaped again wherever it goes into HTML."""
import hashlib
import html
import time

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

PERIODS = ("day", "week", "all")
CACHE_S = 30
_BAD = {c: " " for c in list(range(0, 32)) + list(range(127, 160)) + [0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2028, 0x2029, 0x202a,
        0x202b, 0x202c, 0x202d, 0x202e, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x2066, 0x2067, 0x2068, 0x2069, 0xfeff]}  # controls, zero-width, bidi


def clean_text(x, n):
    """Text from an untrusted machine or player, safe to show: control and invisible characters (including right-to-left overrides
    that make text read backwards) become spaces, runs of spaces collapse, at most n characters."""
    s = str(x if x is not None else "")[: n * 4]  # bound the work first: the input can be 512 KB
    return " ".join(s.translate(_BAD).split())[:n].strip()


def _num(x, lo, hi, kind=int):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:  # not a number, or NaN
        return None
    return kind(min(max(x, lo), hi))


def clean_telemetry(d):
    """What a machine reported, cleaned: {"name", "cpu", "threads", "gpus": [{"name", "vram_mb"}], "os", "idle_gpu"}. ValueError if
    it is not an object."""
    if not isinstance(d, dict):
        raise ValueError("telemetry must be an object")
    gpus = [{"name": clean_text(g.get("name"), 80), "vram_mb": _num(g.get("vram_mb"), 0, 4_000_000) or 0}
            for g in (d.get("gpus") if isinstance(d.get("gpus"), list) else [])[:8] if isinstance(g, dict) and clean_text(g.get("name"), 80)]
    return {"name": clean_text(d.get("name"), 24), "cpu": clean_text(d.get("cpu"), 80), "threads": _num(d.get("threads"), 0, 4096) or 0,
            "gpus": gpus, "os": clean_text(d.get("os"), 32), "idle_gpu": _num(d.get("idle_gpu"), 0, 100, float)}


def node_label(agent):
    """A short stable name for a machine that does not reveal its agent id."""
    return hashlib.sha256(agent.encode()).hexdigest()[:8]


def _vram(mb):
    return "" if not mb else (f"{mb / 1024:.0f} GB" if mb >= 1024 else f"{mb} MB")


def hardware_text(r):
    gpus = ", ".join(f"{g['name']} ({_vram(g['vram_mb'])})" if g["vram_mb"] else g["name"] for g in r["gpus"])
    return " | ".join(x for x in (r["cpu"], gpus, r["os"]) if x)


def render(data, period):
    """The two boards as one small HTML page. Every value is escaped; nothing here runs script."""
    e = html.escape
    nav = " ".join(f'<a href="?period={p}"{" class=on" if p == period else ""}>{label}</a>' for p, label in
                   (("day", "today"), ("week", "last 7 days"), ("all", "all time")))
    t = lambda tokens: f"{tokens['today' if period == 'day' else 'week' if period == 'week' else 'all']:,}"
    nodes = "".join(f"<tr><td>{r['rank']}</td><td>{e(r['name'])}<br><small>{e(r['node'])}</small></td><td>{e(hardware_text(r['reported']))}</td>"
                    f"<td>{'' if r['reported']['idle_gpu_pct'] is None else str(round(r['reported']['idle_gpu_pct'])) + ' %'}</td>"
                    f"<td class=n>{t(r['tokens'])}</td></tr>" for r in data["nodes"]) or "<tr><td colspan=5>No machine has opted in yet.</td></tr>"
    users = "".join(f"<tr><td>{r['rank']}</td><td>{e(r['name'])}</td><td class=n>{r['machines']}</td><td class=n>{t(r['tokens'])}</td></tr>"
                    for r in data["users"]) or "<tr><td colspan=4>No player has opted in yet.</td></tr>"
    return ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Volunteer leaderboard</title><style>body{font:15px system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}"
            "table{border-collapse:collapse;width:100%;margin:.5rem 0 2rem}td,th{padding:.4rem .6rem;border-bottom:1px solid #8884;text-align:left;"
            "vertical-align:top}.n{text-align:right;font-variant-numeric:tabular-nums}small{opacity:.6}a{margin-right:1rem}.on{font-weight:700}</style>"
            f"<h1>Volunteer leaderboard</h1><p>Tokens processed for players. {nav}</p>"
            f"<h2>Machines</h2><table><tr><th>#<th>Machine<th>Hardware (reported by the machine)<th>Idle GPU<th class=n>Tokens"
            f"{nodes}</table><h2>Players</h2><table><tr><th>#<th>Player<th class=n>Machines<th class=n>Tokens{users}</table>"
            "<p><small>Only machines and players that chose to be listed appear. Hardware and idle GPU load are reported by each machine "
            "and are not verified; token counts are measured by the gateway.</small></p>")


def add_routes(app, store):
    cache = {}

    def board(period):
        hit = cache.get(period)
        if not hit or time.monotonic() - hit[0] >= CACHE_S:  # a public page: the database is read at most once per period per CACHE_S
            hit = cache[period] = (time.monotonic(), store.leaderboard(period, 100))
        return hit[1]

    def args(period, limit):
        if period not in PERIODS:
            raise HTTPException(400, "period must be day, week or all")
        data = board(period)
        n = max(1, min(int(limit), 100))
        return {"period": period, **{k: v[:n] for k, v in data.items()}}

    @app.get("/v1/leaderboard")
    async def leaderboard(period: str = "week", limit: int = 25):
        """{"period", "nodes": [...], "users": [...]}, ranked by tokens in the period. Public."""
        return JSONResponse(args(period, limit), headers={"Cache-Control": f"public, max-age={CACHE_S}"})

    @app.get("/leaderboard")
    async def leaderboard_page(period: str = "week", limit: int = 25):
        d = args(period, limit)
        return HTMLResponse(render(d, period), headers={"Cache-Control": f"public, max-age={CACHE_S}", "X-Content-Type-Options": "nosniff",
                                                         "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})
