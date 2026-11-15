"""One-step volunteer setup: checks this machine, picks a model that fits, makes sure Ollama has it, then runs the
node agent. Works on Windows, Linux and macOS (Apple Silicon uses Metal through Ollama).

    python node/join.py --gateway https://gateway.example --token POOL_TOKEN
    python node/join.py --gateway ... --token ... --dry-run        # show the plan, change nothing

It never installs software by itself: if Ollama is missing it tells you where to get it. It downloads one model, only
after saying how big it is and checking the disk. The gateway's token and URL come from whoever runs the pool.
The agent pauses while you use the machine (CPU or GPU above 60 percent; --cpu-limit, --gpu-limit, --ignore-load)."""
import argparse
import asyncio
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from node.agent import JOBS_NOTICE, add_load_args, idle_limits, insecure, serve, telemetry_notice  # noqa: E402

OLLAMA = "http://127.0.0.1:11434"
# (minimum total RAM in GB, model, approximate download in GB). Sizes follow DESIGN.md section 21: the 1 to 2 GB budget
# means the small model on 8 GB machines and the 4B model only from 16 GB.
MODELS = [(16, "qwen3:4b-instruct", 2.5), (6, "qwen3:1.7b", 1.4)]  # not "qwen3:4b": that tag is now a thinking-only model
MIN_RAM_GB = 6


def ram_gb():
    """Total physical memory in GB, or None if it cannot be read."""
    try:
        if sys.platform == "win32":
            class MEM(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = MEM()
            m.length = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 2**30
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / 2**30
        with open("/proc/meminfo") as f:
            return int(f.readline().split()[1]) / 2**20
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None


def pick_model(ram):
    """(model, download GB) for this much RAM, or None if the machine is too small."""
    for need, model, size in MODELS:
        if ram >= need:
            return model, size
    return None


def installed_models(local=OLLAMA, transport=None):
    """Names of models Ollama already has, or None if Ollama is not running."""
    try:
        with httpx.Client(transport=transport, timeout=3) as c:
            r = c.get(local + "/api/tags")
            return {m["name"] for m in r.json().get("models", [])} if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def pull(local, model, transport=None, log=print):
    """Download a model into the Ollama at `local` through its HTTP API, printing progress now and then. True on success.
    The API, not the ollama command: the command may not be on PATH, and it pulls into the default Ollama even when
    --local points at another one."""
    shown = -10
    try:
        with httpx.Client(transport=transport, timeout=httpx.Timeout(30, read=None)) as c:
            with c.stream("POST", local + "/api/pull", json={"model": model, "stream": True}) as r:
                if r.status_code != 200:
                    log(f"Ollama refused the download (HTTP {r.status_code}).")
                    return False
                for line in r.iter_lines():
                    d = json.loads(line) if line.strip() else {}
                    if d.get("error"):
                        log(f"Ollama: {d['error']}")
                        return False
                    if d.get("total") and d.get("completed") is not None and d["completed"] * 100 // d["total"] >= shown + 10:
                        shown = d["completed"] * 100 // d["total"]
                        log(f"  downloading {model}: {shown}%")
                    if d.get("status") == "success":
                        return True
    except (httpx.HTTPError, ValueError) as e:
        log(f"Download interrupted: {e}")
    return False


def install_hint():
    return {"win32": "Install Ollama from https://ollama.com/download/windows (or: winget install Ollama.Ollama).",
            "darwin": "Install Ollama from https://ollama.com/download/mac (or: brew install ollama)."}.get(
        sys.platform, "Install Ollama from https://ollama.com/download/linux, then start it (ollama serve).")


def plan(a, ram, have):
    """The steps this run would take, as (ok, text) lines. have = installed model names or None."""
    steps = []
    if ram is None:
        steps.append((True, "Could not read total RAM; continuing with the small model."))
        ram = MIN_RAM_GB
    choice = (a.model, 0) if a.model else pick_model(ram)
    if not choice:
        return [(False, f"This machine has {ram:.1f} GB of RAM; at least {MIN_RAM_GB} GB is needed.")], None
    model, size = choice
    steps.append((True, f"RAM {ram:.1f} GB -> model {model}" + ("" if a.model else f" (about {size} GB download)")))
    if have is None:
        steps.append((False, "Ollama is not running. " + install_hint()))
    elif model in have or any(h.startswith(model + ":") for h in have):
        steps.append((True, f"{model} is already installed."))
    else:
        steps.append((True, f"Will download {model} into Ollama."))
    steps.append((True, f"Will connect out to {a.gateway} with {a.slots} worker(s). No port is opened on this machine."))
    if getattr(a, "telemetry", False):
        urls = [u.strip() for u in a.gateway.split(",") if u.strip()]
        steps.append((not any(insecure(u) for u in urls), "Will report your CPU and GPU model and idle GPU load to the anonymous network "
                      "statistics (stop with agent.py --telemetry-off); this needs an https:// gateway address."))
    else:
        steps.append((True, "Not in the network statistics. To add this machine, add --telemetry."))
    return steps, model


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", required=True, help="gateway URL; several gateway machines sharing one database: comma-separated")
    ap.add_argument("--token", required=True)
    ap.add_argument("--model", help="override the automatic choice (the gateway must expect this model)")
    ap.add_argument("--slots", type=int, default=1)
    ap.add_argument("--local", default=OLLAMA)
    ap.add_argument("--dry-run", action="store_true", help="show the plan and stop")
    ap.add_argument("--telemetry", action="store_true", help="opt in to the anonymous network statistics: report CPU and GPU model and idle GPU load")
    add_load_args(ap)
    return ap


def main():
    a = parser().parse_args()
    print(f"Anansi volunteer setup on {platform.system()} {platform.machine()}")
    steps, model = plan(a, ram_gb(), installed_models(a.local))
    for ok, text in steps:
        print(("  ok   " if ok else "  FAIL ") + text)
    if not all(ok for ok, _ in steps):
        sys.exit(2)
    if a.dry_run:
        print("Dry run: nothing changed.")
        return
    have = installed_models(a.local) or set()
    if not (model in have or any(h.startswith(model + ":") for h in have)):
        size = dict((m, s) for _, m, s in MODELS).get(model, 2.0)
        free = shutil.disk_usage(os.path.expanduser("~")).free / 2**30
        if free < size * 1.5:
            sys.exit(f"Not enough free disk: {free:.1f} GB free, about {size * 1.5:.1f} GB needed.")
        if not pull(a.local, model):
            sys.exit("The model download failed. Check your connection and run this again; it resumes where it stopped.")
    print(JOBS_NOTICE)
    if a.telemetry:
        print(telemetry_notice([u.strip() for u in a.gateway.split(",") if u.strip()]))
    print("Starting. Press Ctrl+C to stop.")

    async def run():
        gws = [httpx.AsyncClient(base_url=u.strip().rstrip("/")) for u in a.gateway.split(",") if u.strip()]
        async with httpx.AsyncClient(base_url=a.local) as local:
            try:
                await serve(gws, local, a.token, a.slots, model=model, idle=idle_limits(a), telemetry_on=a.telemetry)
            finally:
                for g in gws:
                    await g.aclose()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
