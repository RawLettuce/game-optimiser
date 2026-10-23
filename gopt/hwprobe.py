"""Root free hardware and environment probe with a fingerprint cache.

Every external command is optional: a missing tool leaves its field null.
Nothing here changes anything except the tool's own cache file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import __version__

VOLATILE = {"probed_at", "gopt_version"}


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def cpu_info(cpuinfo: str | None = None) -> dict:
    text = cpuinfo if cpuinfo is not None else _read("/proc/cpuinfo") or ""
    model = None
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    threads = text.count("processor\t:") + text.count("processor :")
    cores = None
    m = re.search(r"cpu cores\s*:\s*(\d+)", text)
    if m:
        cores = int(m.group(1))
    return {"model": model, "cores": cores, "threads": threads or None}


def mem_info(meminfo: str | None = None) -> dict:
    text = meminfo if meminfo is not None else _read("/proc/meminfo") or ""
    m = re.search(r"MemTotal:\s*(\d+)\s*kB", text)
    return {"total_mb": int(m.group(1)) // 1024 if m else None}


def gpu_info(smi_out: str | None = None, smi_q: str | None = None) -> dict:
    out = smi_out if smi_out is not None else _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version,pci.bus_id", "--format=csv,noheader"])
    info = {"vendor": None, "name": None, "vram_mb": None, "driver": None, "pci": None, "bar1_mb": None,
            "resizable_bar": None}
    if out:
        parts = [p.strip() for p in out.strip().splitlines()[0].split(",")]
        if len(parts) >= 3:
            info.update(vendor="nvidia", name=parts[0], driver=parts[2])
            m = re.search(r"(\d+)", parts[1])
            info["vram_mb"] = int(m.group(1)) if m else None
            if len(parts) >= 4:
                info["pci"] = parts[3]
        q = smi_q if smi_q is not None else _run(["nvidia-smi", "-q", "-d", "MEMORY"])
        if q:
            m = re.search(r"BAR1 Memory Usage\s*\n\s*Total\s*:\s*(\d+)\s*MiB", q)
            if m:
                info["bar1_mb"] = int(m.group(1))
                if info["vram_mb"]:
                    info["resizable_bar"] = info["bar1_mb"] >= info["vram_mb"] * 0.9
    return info


def parse_kscreen(text: str) -> list[dict]:
    """Parse `kscreen-doctor -o` plain output into outputs with the active mode."""
    outputs = []
    cur = None
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    for raw in text.splitlines():
        line = ansi.sub("", raw).strip()
        m = re.match(r"Output:\s*(\d+)\s+(\S+)", line)
        if m:
            cur = {"id": int(m.group(1)), "name": m.group(2), "enabled": None, "scale": None,
                   "active_mode": None, "refresh_hz": None, "width": None, "height": None, "hdr": None}
            outputs.append(cur)
            line = line[m.end():]      # the rest of the line may hold the other fields
        if cur is None:
            continue
        # kscreen-doctor prints one item per line in a terminal and everything on one line when piped,
        # so every pattern is searched anywhere in the line.
        if re.search(r"\benabled\b", line) and cur["enabled"] is None:
            cur["enabled"] = True
        if re.search(r"\bdisabled\b", line) and not re.search(r"HDR:\s*disabled|Gamut:\s*disabled", line) and cur["enabled"] is None:
            cur["enabled"] = False
        ms = re.search(r"Scale:\s*([0-9.]+)", line)
        if ms:
            cur["scale"] = float(ms.group(1))
        mh = re.search(r"HDR:\s*(\w+)", line)
        if mh:
            cur["hdr"] = mh.group(1).lower() == "enabled"
        m2 = re.search(r"(\d+)x(\d+)@(\d+)\*", line)
        if m2 and ("Modes:" in line or cur["active_mode"] is None):
            cur["width"], cur["height"], cur["refresh_hz"] = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            cur["active_mode"] = f"{m2.group(1)}x{m2.group(2)}@{m2.group(3)}"
    return outputs


def display_info(kscreen_out: str | None = None) -> dict:
    out = kscreen_out if kscreen_out is not None else _run(["kscreen-doctor", "-o"])
    outputs = parse_kscreen(out) if out else []
    drm = []
    for p in sorted(Path("/sys/class/drm").glob("card*-*")) if Path("/sys/class/drm").exists() else []:
        status = _read(str(p / "status"))
        if status and status.strip() == "connected":
            drm.append({"connector": p.name.split("-", 1)[1], "modes": (_read(str(p / "modes")) or "").split()[:3]})
    return {"outputs": outputs, "drm_connected": drm,
            "session": os.environ.get("XDG_SESSION_TYPE"), "desktop": os.environ.get("XDG_CURRENT_DESKTOP")}


def tools_info() -> dict:
    mh = _run(["mangohud", "--version"]) or ""
    return {"mangohud": shutil.which("mangohud") is not None, "mangohud_version": mh.strip() or None,
            "gamescope": shutil.which("gamescope") is not None, "gamemoderun": shutil.which("gamemoderun") is not None,
            "kscreen_doctor": shutil.which("kscreen-doctor") is not None, "python": ".".join(map(str, os.sys.version_info[:3]))}


def probe() -> dict:
    return {"gopt_version": __version__, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cpu": cpu_info(), "memory": mem_info(), "gpu": gpu_info(), "display": display_info(),
            "tools": tools_info(), "os": (_read("/etc/os-release") or "").splitlines()[:3]}


def fingerprint(data: dict) -> str:
    stable = {k: v for k, v in data.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]


def update_cache(data: dict, cache_path: Path) -> tuple[str, bool]:
    """Write the cache only when the fingerprint changed. Returns (fingerprint, refreshed)."""
    fp = fingerprint(data)
    cache_path = Path(cache_path)
    if cache_path.exists():
        try:
            old = json.loads(cache_path.read_text())
            if old.get("fingerprint") == fp:
                return fp, False
            prev = cache_path.with_name(cache_path.stem + ".prev.json")
            prev.write_text(cache_path.read_text())
        except (OSError, ValueError):
            pass
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fingerprint": fp, **data}, indent=2))
    os.replace(tmp, cache_path)
    return fp, True


def active_output(data: dict, name: str) -> dict | None:
    for o in data.get("display", {}).get("outputs", []):
        if o.get("name") == name:
            return o
    return None
