"""Volunteer node agent: connects OUT to an Anansi gateway, polls for jobs and runs them on a local
OpenAI-compatible server (Ollama, llama-server, vLLM). No inbound port, so it works behind home NAT.
Run: python node/agent.py --gateway https://gw.example --token TOKEN --local http://127.0.0.1:11434 [--slots 2]
It pauses while the owner is busy (CPU or GPU above 60 percent; --cpu-limit, --gpu-limit, --ignore-load).
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

ALLOWED = "/v1/chat/completions"
JOBS = {"active": 0, "last": 0.0}  # jobs this process is running, and when the last one ended (their load is ours, not the owner's)
SETTLE_S = 15


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


async def worker(gw, local, token, agent, log=print, model=None, idle=None, check_s=10):
    """idle = (cpu %, gpu %) limits: while the machine is busier than that and none of our own jobs are running, this worker
    does not register or poll, so no job is sent to it (the gateway forgets it within seconds and re-checks it when it returns).
    shortcut: load right after our own job is ignored for SETTLE_S seconds; a job queued just before the pause waits for
    the gateway's timeout and is retried on another node."""
    H, nid, backoff, paused = {"X-Node-Token": token, "X-Node-Agent": agent}, None, 1, False
    while True:
        if idle and JOBS["active"] == 0 and time.monotonic() - JOBS["last"] > SETTLE_S:
            if await machine_busy(*idle):
                if not paused:
                    log("this machine is busy, pausing until it is idle")
                paused = True
                await asyncio.sleep(check_s)
                continue
        if paused:
            log("this machine is idle again, resuming")
            paused = False
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
            if r.status_code == 404:  # the gateway forgot us (restart or idle too long)
                nid = None
                continue
            r.raise_for_status()
            backoff = 1
            if r.status_code != 200:
                continue
            job = r.json()
            res = {"status": 400, "body": "", "content_type": "text/plain"}
            if job["path"] == ALLOWED:
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


async def serve(gw, local, token, slots=1, log=print, agent=None, model=None, idle=None):
    agent = agent or agent_id()
    await asyncio.gather(*[worker(gw, local, token, agent, log, model, idle) for _ in range(slots)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--local", default="http://127.0.0.1:11434")
    ap.add_argument("--slots", type=int, default=1)
    ap.add_argument("--model", help="local model name to run every job on (default: the name the gateway sends)")
    add_load_args(ap)
    a = ap.parse_args()

    async def main():
        async with httpx.AsyncClient(base_url=a.gateway) as gw, httpx.AsyncClient(base_url=a.local) as local:
            await serve(gw, local, a.token, a.slots, model=a.model, idle=idle_limits(a))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
