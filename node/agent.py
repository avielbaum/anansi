"""Volunteer node agent: connects OUT to an Anansi gateway, polls for jobs and runs them on a local
OpenAI-compatible server (Ollama, llama-server, vLLM). No inbound port, so it works behind home NAT.
Run: python node/agent.py --gateway https://gw.example --token TOKEN --local http://127.0.0.1:11434 [--slots 2]
It pauses while the owner is busy (CPU or GPU above 60 percent; --cpu-limit, --gpu-limit, --ignore-load).
To earn credits: run once with --link and type the printed code into a game that uses Anansi.
To add this machine to the anonymous network statistics: --telemetry (CPU and GPU model, idle GPU load; no name); --telemetry-off removes it.
Each slot registers as its own worker. It only ever forwards /v1/chat/completions to the local server.
Works the same on Windows, Linux and macOS (Apple Silicon: Ollama and llama.cpp use Metal).
shortcut: the token is a shared secret per pool, not a per-user, platform-bound certificate (DESIGN.md section 9)."""
import argparse
import asyncio
import glob
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import time

import httpx

try:
    from node import hardware
except ImportError:  # run as a script (python node/agent.py): its folder is on the path, not the repo
    import hardware

ALLOWED = "/v1/chat/completions"
JOBS = {"active": 0, "last": 0.0}  # jobs this process is running, and when the last one ended (their load is ours, not the owner's)
REPORT_S = 300  # how often --telemetry sends its report
SAMPLE_S = 30  # how often it samples the GPU while none of our jobs run
GRACE_S = 180  # the first report waits this long for a first sample, then goes without one (a GPU that cannot be read)
IDLE = {"gpu": None}  # the owner's GPU load, smoothed, measured only while none of our jobs run
SETTLE_S = 5  # our own load must fade before a reading means the owner's (GPU samples ~1 s; Linux CPU is a 1-min average)
FORCE_S = 60  # with jobs arriving nonstop the machine is never idle long enough to check, so force a check this often
CHECK = {"due": 0.0, "drain": False, "paused": False}  # shared by all workers: the machine pauses as one


def cpu_busy_fraction():
    """CPU use from 0 to 1: sampled over half a second on Windows, the 1-minute load per core on Linux and macOS.
    None if it cannot be measured (then the machine is never treated as busy)."""
    if hasattr(os, "getloadavg"):
        return min(1.0, os.getloadavg()[0] / (os.cpu_count() or 1))
    try:
        import ctypes
        from ctypes import wintypes

        def sample():
            idle, kern, user = (wintypes.FILETIME() for _ in range(3))
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
            return [(f.dwHighDateTime << 32) | f.dwLowDateTime for f in (idle, kern, user)]
        a = sample()
        time.sleep(0.5)
        b = sample()
        total = (b[1] - a[1]) + (b[2] - a[2])  # kernel time includes idle time
        return max(0.0, 1 - (b[0] - a[0]) / total) if total else None
    except (AttributeError, OSError, ImportError):
        return None


def gpu_util():
    """Highest GPU load in percent from every reader that works on this machine, or None if none does.
    NVIDIA anywhere (nvidia-smi); any vendor on Windows (the system's GPU engine counters); AMD on Linux (amdgpu sysfs);
    Apple Silicon and other Mac GPUs (ioreg). shortcut: Intel GPUs on Linux are not measured (no plain file to read)."""
    vals = [v for v in (_nvidia_util(), _windows_gpu_util(), _amd_linux_util(), _mac_gpu_util()) if v is not None]
    return max(vals) if vals else None


def _nvidia_util():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=3).stdout
        return max(float(x) for x in out.split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def busiest_engine(samples):
    """samples = (counter instance name, percent) from Windows' "GPU Engine" counters, one per process and engine.
    An engine's load is the sum over processes; the GPU's load is its busiest engine (3D, video, copy, compute)."""
    per = {}
    for name, v in samples:
        m = re.search(r"(luid_\w+?_phys_\d+_eng_\d+)", name)
        if m:
            per[m.group(1)] = per.get(m.group(1), 0.0) + v
    return min(100.0, max(per.values())) if per else None


def _windows_gpu_util():
    """Every GPU vendor on Windows 10 1709+, through the same counters Task Manager shows. English counter names, so
    it works on any display language. Samples over one second."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Value(ctypes.Structure):  # PDH_FMT_COUNTERVALUE: status, then a union whose double sits at offset 8
            _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]

        class Item(ctypes.Structure):
            _fields_ = [("name", wintypes.LPWSTR), ("v", Value)]
        pdh, q, c = ctypes.WinDLL("pdh"), ctypes.c_void_p(), ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)):
            return None
        try:
            if pdh.PdhAddEnglishCounterW(q, r"\GPU Engine(*)\Utilization Percentage", None, ctypes.byref(c)):
                return None
            pdh.PdhCollectQueryData(q)
            time.sleep(1.0)
            pdh.PdhCollectQueryData(q)
            size, n, double = wintypes.DWORD(0), wintypes.DWORD(0), 0x200  # PDH_FMT_DOUBLE
            pdh.PdhGetFormattedCounterArrayW(c, double, ctypes.byref(size), ctypes.byref(n), None)
            buf = (ctypes.c_byte * size.value)()
            if pdh.PdhGetFormattedCounterArrayW(c, double, ctypes.byref(size), ctypes.byref(n), buf):
                return None
            items = ctypes.cast(buf, ctypes.POINTER(Item))
            return busiest_engine((items[i].name, items[i].v.value) for i in range(n.value))
        finally:
            pdh.PdhCloseQuery(q)
    except (AttributeError, OSError, ImportError):
        return None


def _amd_linux_util(pattern="/sys/class/drm/card*/device/gpu_busy_percent"):
    vals = []
    for p in glob.glob(pattern):  # written by the amdgpu driver, readable without root
        try:
            vals.append(float(open(p).read().strip()))
        except (OSError, ValueError):
            pass
    return max(vals) if vals else None


def mac_utilisation(ioreg_text):
    """Highest "Device Utilization %" in `ioreg -r -d 1 -c IOAccelerator` output, or None."""
    vals = [float(x) for x in re.findall(r'"Device Utilization %"\s*=\s*(\d+)', ioreg_text)]
    return max(vals) if vals else None


def _mac_gpu_util():
    if sys.platform != "darwin":
        return None
    try:  # UNTESTED on a Mac. [verify] Needs no root; the key is present on Apple Silicon and recent Intel Macs.
        out = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True, text=True, timeout=3).stdout
        return mac_utilisation(out)
    except (OSError, subprocess.SubprocessError):
        return None


async def machine_busy(cpu_limit, gpu_limit):
    """True if the owner seems to be using the machine: CPU or GPU above the limit (percent)."""
    cpu, gpu = await asyncio.to_thread(cpu_busy_fraction), await asyncio.to_thread(gpu_util)
    return (cpu is not None and cpu * 100 > cpu_limit) or (gpu is not None and gpu > gpu_limit)


def agent_id(path=pathlib.Path.home() / ".anansi-agent-id"):
    """Stable random id for this installation, created on first run. The gateway bans by this id."""
    if not path.exists():
        path.write_text(secrets.token_hex(16))
    return path.read_text().strip()


async def worker(gw, local, token, agent, log=print, model=None, idle=None, check_s=10, slot=None):
    """idle = (cpu %, gpu %) limits: while the machine is busier than that and none of our own jobs are running, this worker
    does not register or poll, so no job is sent to it (the gateway forgets it within seconds and re-checks it when it returns).
    Under nonstop traffic the machine is never settled, so every FORCE_S all workers stop taking jobs for about SETTLE_S
    and the load is read then. shortcut: a job queued just before the pause waits for the gateway's timeout and is retried
    on another node; a busy pool loses up to SETTLE_S of every FORCE_S of this machine's time."""
    H, nid, backoff = {"X-Node-Token": token, "X-Node-Agent": agent}, None, 1
    while True:
        if idle:
            if not CHECK["paused"] and time.monotonic() >= CHECK["due"]:
                CHECK["drain"] = True  # found on a real GPU: under steady traffic the owner's game was never noticed
            if JOBS["active"] == 0 and time.monotonic() - JOBS["last"] > SETTLE_S:
                busy = await machine_busy(*idle)
                CHECK["drain"], CHECK["due"] = False, time.monotonic() + FORCE_S
                if busy != CHECK["paused"]:  # one decision for the machine: a worker kept busy by jobs must pause too
                    CHECK["paused"] = busy
                    log("this machine is busy, pausing until it is idle" if busy else "this machine is idle again, resuming")
            if CHECK["paused"] or CHECK["drain"]:
                if CHECK["paused"] and nid is not None:  # tell the gateway, or it queues jobs for us until its timeout
                    try:
                        await gw.post("/node/leave", params={"node_id": nid}, headers=H)
                    except httpx.HTTPError:
                        pass  # the gateway forgets a silent node within its TTL anyway
                    nid = None
                await asyncio.sleep(check_s if CHECK["paused"] else 0.5)  # no new job while paused or draining
                continue
        try:
            if nid is None:
                r = await gw.post("/node/register", headers=H)
                if r.status_code == 403:
                    log("this agent id is banned by the gateway")
                    return
                r.raise_for_status()
                nid, poll_s = r.json()["node_id"], r.json()["poll_s"]
                log(f"registered as {nid}")
            r = await gw.get("/node/poll", params={"node_id": nid}, headers=H, timeout=poll_s + 10)
            if r.status_code == 404:  # the gateway forgot or dropped us (restart, idle too long, a probe with no answer)
                nid = None
                await asyncio.sleep(backoff)  # without it a dropped node re-registers and is re-probed in a tight loop
                backoff = min(backoff * 2, 30)
                continue
            r.raise_for_status()
            backoff = 1
            if r.status_code != 200:
                continue
            job = r.json()
            res = {"status": 400, "body": "", "content_type": "text/plain"}
            if job["path"] == ALLOWED:
                await slot.acquire() if slot else None  # one limit for the machine, however many gateways send work
                JOBS["active"] += 1
                try:
                    body = job["body"]
                    if model:  # the gateway names the pool's model; run whichever model this machine actually has
                        body = json.dumps({**json.loads(body), "model": model})
                    lr = await local.post(ALLOWED, content=body, headers={"content-type": "application/json"},
                                          timeout=120)
                    res = {"status": lr.status_code, "body": lr.text,
                           "content_type": lr.headers.get("content-type", "application/json")}
                except httpx.HTTPError:
                    res["status"] = 502
                finally:
                    JOBS["active"] -= 1
                    JOBS["last"] = time.monotonic()
                    slot.release() if slot else None
            await gw.post("/node/result", json={"node_id": nid, "job": job["job"], **res}, headers=H)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:  # also a reply that is not the JSON we expect
            nid = None if not isinstance(e, httpx.HTTPError) else nid
            log(f"gateway unreachable or sent junk ({e.__class__.__name__}), retrying in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def add_load_args(ap):
    """The busy-machine options, shared with node/join.py so both start the agent the same way."""
    ap.add_argument("--cpu-limit", type=float, default=60, help="pause while CPU use is above this percent (default 60)")
    ap.add_argument("--gpu-limit", type=float, default=60, help="pause while GPU use is above this percent (default 60)")
    ap.add_argument("--ignore-load", action="store_true", help="serve jobs even when the machine is busy")


def idle_limits(a):
    return None if a.ignore_load else (a.cpu_limit, a.gpu_limit)


JOBS_NOTICE = ("This machine will answer game dialogue written by players: their messages are sent to your local model. "
               "Do not log, keep, read or share them (docs/volunteer-terms.md).")


def insecure(url):
    """True for a plain-http gateway address that is not this machine: whatever is sent there, a leaderboard report included, can be
    read on the way."""
    u = httpx.URL(url)
    return u.scheme != "https" and u.host not in ("localhost", "127.0.0.1", "::1")


def telemetry_notice(urls):
    """Said at every start with --telemetry: exactly what is sent, to whom, and what happens to it."""
    return (f"Statistics telemetry is ON for {', '.join(urls)}. About every 5 minutes this agent sends your CPU model, GPU models and memory, "
            "an operating system name and a slow average of how busy your GPU is when this agent is not using it. It sends no name, account or "
            "address. The gateway publishes only statistics for groups of machines with the same hardware (never a single machine), but it keeps "
            "your latest report under this agent's random id for up to 2 days so it can update it. See exactly what is sent: --telemetry-show. "
            "Stop and delete it any time: --telemetry-off.")


def telemetry_preview():
    """The report as it would be sent, with the GPU load read right now (the real one is a slow average)."""
    return json.dumps({**hardware.describe(), "idle_gpu": gpu_util()}, indent=2)


async def telemetry(gw, token, agent, log=print):
    """Opt-in (--telemetry): tell the gateway what this machine is and how busy its GPU is when none of our jobs run, for the anonymous
    network statistics. The load is sampled only while idle, so it is the owner's own use, and smoothed so one spike does not stand for the
    machine. A report the gateway refuses (not registered yet) is retried at the next sample."""
    H = {"X-Node-Token": token, "X-Node-Agent": agent}
    info = await asyncio.to_thread(hardware.describe)
    last, started = None, time.monotonic()
    while True:
        if JOBS["active"] == 0 and time.monotonic() - JOBS["last"] > SETTLE_S:
            g = await asyncio.to_thread(gpu_util)
            if g is not None:
                IDLE["gpu"] = g if IDLE["gpu"] is None else 0.7 * IDLE["gpu"] + 0.3 * g
        # the probe the gateway sends on registration keeps our model busy for the first seconds: the first report waits for a sample
        if (IDLE["gpu"] is not None or time.monotonic() - started > GRACE_S) if last is None else time.monotonic() - last >= REPORT_S:
            try:
                r = await gw.post("/node/telemetry", json={**info, "idle_gpu": IDLE["gpu"]}, headers=H)
                if r.status_code == 200:
                    last = time.monotonic()
                elif r.status_code == 403 and any(w in r.text for w in ("banned", "switched off")):
                    try:
                        why = r.json()["detail"]
                    except (ValueError, KeyError):
                        why = r.text
                    log(f"the gateway will not take statistics from this machine ({why})")
                    return
            except httpx.HTTPError:
                pass  # unreachable: the next sample tries again
        await asyncio.sleep(SAMPLE_S)


async def serve(gw, local, token, slots=1, log=print, agent=None, model=None, idle=None, telemetry_on=False):
    """gw: one gateway client, or a list of them (one per gateway machine sharing a database). Every gateway gets `slots`
    workers so none waits for another's long poll; at most `slots` jobs run on the local model at once across all of them.
    telemetry_on: also send the anonymous hardware and idle-load report to every gateway."""
    agent = agent or agent_id()
    gws = gw if isinstance(gw, (list, tuple)) else [gw]
    slot = asyncio.Semaphore(slots)
    await asyncio.gather(*[worker(g, local, token, agent, log if len(gws) == 1 else (lambda m, u=str(g.base_url): log(f"[{u}] {m}")),
                                  model, idle, slot=slot) for g in gws for _ in range(slots)],
                         *([telemetry(g, token, agent, log) for g in gws] if telemetry_on else []))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True, help="gateway URL; several gateway machines sharing one database: comma-separated")
    ap.add_argument("--token", required=True)
    ap.add_argument("--local", default="http://127.0.0.1:11434")
    ap.add_argument("--slots", type=int, default=1)
    ap.add_argument("--model", help="local model name to run every job on (default: the name the gateway sends)")
    ap.add_argument("--link", action="store_true", help="print a code to type into a game, so this machine earns credits for you")
    ap.add_argument("--telemetry", action="store_true", help="opt in to the anonymous network statistics: report CPU and GPU model and idle GPU load")
    ap.add_argument("--telemetry-off", action="store_true", help="delete what this machine reported, then exit")
    ap.add_argument("--telemetry-show", action="store_true", help="print exactly what --telemetry would send and exit; nothing is sent")
    add_load_args(ap)
    a = ap.parse_args()
    urls = [u.strip().rstrip("/") for u in a.gateway.split(",") if u.strip()]
    if a.telemetry_show:
        print(telemetry_notice(urls) + "\n\nA report looks like this (the real GPU load is a slow average, and the gateway averages again):")
        print(telemetry_preview())
        raise SystemExit
    if a.telemetry and any(insecure(u) for u in urls):
        raise SystemExit("--telemetry sends your hardware details, so the gateway address must start with https:// (or be this machine). Not started.")
    if a.telemetry_off:
        for u in urls:
            r = httpx.delete(u + "/node/telemetry", headers={"X-Node-Token": a.token, "X-Node-Agent": agent_id()}, timeout=20)
            print(f"{u}: {'deleted' if r.status_code == 200 else 'HTTP ' + str(r.status_code)}")
        raise SystemExit
    if a.link:  # codes live in the shared database, so any one gateway can issue them
        r = httpx.post(urls[0] + "/node/link-code", headers={"X-Node-Token": a.token, "X-Node-Agent": agent_id()}, timeout=20)
        r.raise_for_status()
        d = r.json()
        print(f"Type this code into a game that uses Anansi within {d['expires_s'] // 60} minutes: {d['code']}")
        raise SystemExit

    print(JOBS_NOTICE)
    if a.telemetry:
        print(telemetry_notice(urls))

    async def main():
        gws = [httpx.AsyncClient(base_url=u) for u in urls]
        async with httpx.AsyncClient(base_url=a.local) as local:
            try:
                await serve(gws, local, a.token, a.slots, model=a.model, idle=idle_limits(a), telemetry_on=a.telemetry)
            finally:
                for g in gws:
                    await g.aclose()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
