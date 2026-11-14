"""What this machine is, for the leaderboard (`node/agent.py --telemetry`): CPU model, GPU models with video memory, and a coarse
operating system name. Nothing else: no hostname, user name, address, serial number or driver version.
Each reader is a thin function around a parser that takes the command's output, so every platform's format is tested without
that platform. Windows and Linux/NVIDIA have been run on real machines; the macOS and AMD readers follow the documented formats and
have not (no Mac or AMD GPU was available). Every reader returns an empty or "unknown" answer instead of failing."""
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys

VIRTUAL = re.compile(r"microsoft (basic|remote|hyper-v)|virtual|vmware|parsec|citrix|displaylink|indirect display", re.I)


def _run(cmd, timeout=8):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_cpuinfo(text):
    """The model name from Linux /proc/cpuinfo (x86 "model name", ARM "Model name" or "Hardware"), or ""."""
    m = re.search(r"(?im)^(?:model name|hardware)\s*:\s*(.+)$", text)
    return m.group(1).strip() if m else ""


def cpu_model():
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        elif sys.platform == "darwin":
            name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        else:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                name = parse_cpuinfo(f.read())
    except (OSError, ImportError, AttributeError):
        name = ""
    return " ".join(name.split()) or platform.processor() or platform.machine() or "unknown"


def parse_nvidia(out):
    """`nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` -> [{"name", "vram_mb"}]."""
    gpus = []
    for line in out.splitlines():
        name, _, mem = line.rpartition(",")
        if name.strip() and mem.strip().isdigit():
            gpus.append({"name": name.strip(), "vram_mb": int(mem)})
    return gpus


def parse_cim(text, skip_nvidia=False):
    """Windows `Get-CimInstance Win32_VideoController | Select Name,AdapterRAM | ConvertTo-Json` -> gpus. AdapterRAM is a 32-bit
    field that tops out at 4 GB, so a value at that ceiling (or none) is reported as 0 = unknown."""
    try:
        d = json.loads(text)
    except ValueError:
        return []
    out = []
    for x in d if isinstance(d, list) else [d]:
        name = str(x.get("Name") or "").strip() if isinstance(x, dict) else ""
        if not name or VIRTUAL.search(name) or (skip_nvidia and "nvidia" in name.lower()):
            continue
        ram = x.get("AdapterRAM")
        out.append({"name": name, "vram_mb": int(ram) // 2**20 if isinstance(ram, int) and 0 < ram < 4 * 2**30 - 2**20 else 0})
    return out


def parse_profiler(text):
    """macOS `system_profiler SPDisplaysDataType -json` -> gpus (Apple Silicon reports no separate video memory: 0 = unknown)."""
    try:
        items = json.loads(text).get("SPDisplaysDataType") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for x in items:
        name = str(x.get("sppci_model") or x.get("_name") or "").strip() if isinstance(x, dict) else ""
        m = re.match(r"\s*(\d+)\s*(GB|MB)", str(x.get("spdisplays_vram") or x.get("spdisplays_vram_shared") or "")) if name else None
        if name:
            out.append({"name": name, "vram_mb": int(m.group(1)) * (1024 if m.group(2) == "GB" else 1) if m else 0})
    return out


def amd_sysfs(base="/sys/class/drm"):
    """AMD GPUs from sysfs (vendor 0x1002): video memory from mem_info_vram_total, name from product_name when the driver gives it."""
    out = []
    for dev in sorted(glob.glob(os.path.join(base, "card[0-9]*", "device"))):
        try:
            if open(os.path.join(dev, "vendor")).read().strip() != "0x1002":
                continue
            vram = int(open(os.path.join(dev, "mem_info_vram_total")).read().strip()) // 2**20
            try:
                name = open(os.path.join(dev, "product_name")).read().strip()
            except OSError:
                name = "AMD GPU " + open(os.path.join(dev, "device")).read().strip()
            out.append({"name": name, "vram_mb": vram})
        except (OSError, ValueError):
            continue
    return out


def gpus():
    found = []
    exe = shutil.which("nvidia-smi")
    if exe:
        found += parse_nvidia(_run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))
    if sys.platform == "win32":
        found += parse_cim(_run(["powershell", "-NoProfile", "-Command",
                                 "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"]),
                           skip_nvidia=bool(found))
    elif sys.platform == "darwin":
        found += parse_profiler(_run(["system_profiler", "SPDisplaysDataType", "-json"]))
    else:
        found += amd_sysfs()
    return found


def os_label():
    """A coarse name: "Windows 10", "Linux", "macOS". No build number, no hostname."""
    return {"win32": "Windows " + platform.release(), "darwin": "macOS"}.get(sys.platform, "Linux" if sys.platform.startswith("linux") else sys.platform)


def describe():
    return {"cpu": cpu_model(), "threads": os.cpu_count() or 0, "gpus": gpus(), "os": os_label()}
