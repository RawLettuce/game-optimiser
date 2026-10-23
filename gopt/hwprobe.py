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


def _hz(r: float) -> float:
    return round(float(r), 2)


def _mode(w: int, h: int, r: float) -> str:
    """'3840x2160@240' or '2560x1440@99.95': whole numbers lose the decimals."""
    hz = _hz(r)
    return f"{w}x{h}@{int(round(hz)) if abs(hz - round(hz)) < 0.02 else f'{hz:.2f}'}"


def _new_output(oid, name) -> dict:
    return {"id": oid, "name": name, "enabled": None, "connected": None, "priority": None, "scale": None,
            "pos": None, "active_mode": None, "refresh_hz": None, "width": None, "height": None,
            "preferred_mode": None, "max_mode": None, "modes": [], "hdr": None, "vrr": None}


def _finish_modes(o: dict, modes: list[tuple[int, int, float]], current, preferred):
    """Fill the mode fields from (w, h, hz) tuples: deduplicated, largest and fastest first."""
    uniq = sorted(set((w, h, _hz(r)) for w, h, r in modes), key=lambda m: (m[0] * m[1], m[2]), reverse=True)
    o["modes"] = [_mode(*m) for m in uniq]
    o["max_mode"] = o["modes"][0] if o["modes"] else None
    if current:
        w, h, r = current
        o.update(width=w, height=h, refresh_hz=_hz(r), active_mode=_mode(w, h, r))
    if preferred:
        o["preferred_mode"] = _mode(*preferred)


MODE_RE = re.compile(r"(\d+):(\d+)x(\d+)@([\d.]+)(\*?)(!?)")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def parse_kscreen(text: str) -> list[dict]:
    """Parse `kscreen-doctor -o` text (libkscreen doctor.cpp showOutputs).

    Each output starts with 'Output: <id> <name> <uuid>' and is followed by one item per line.
    Modes are printed as 'id:WxH@RR.RR', the current one with '*', the preferred one with '!'
    (doctor.cpp prints the refresh with two decimals: '240.00*'). Terminal colour codes are removed.
    Also accepts the older one line form.
    """
    outputs = []
    text = ANSI_RE.sub("", text)
    for rec in re.split(r"(?m)(?=^\s*Output:)", text):
        m = re.match(r"\s*Output:\s*(\d+)\s+(\S+)", rec)
        if not m:
            continue
        o = _new_output(int(m.group(1)), m.group(2))
        body = rec[m.end():]
        st = re.search(r"(?:^|\s)(enabled|disabled)\s+(connected|disconnected)\b", body)
        if st:
            o["enabled"], o["connected"] = st.group(1) == "enabled", st.group(2) == "connected"
        mp = re.search(r"\bpriority\s+(\d+)", body)
        if mp:
            o["priority"] = int(mp.group(1))
        ms = re.search(r"Scale:\s*([0-9.]+)", body)
        if ms:
            o["scale"] = float(ms.group(1))
        mg = re.search(r"Geometry:\s*(-?\d+),(-?\d+)", body)
        if mg:
            o["pos"] = [int(mg.group(1)), int(mg.group(2))]
        mh = re.search(r"HDR:\s*(\w+)", body)
        if mh:
            o["hdr"] = mh.group(1).lower() == "enabled"
        mv = re.search(r"Vrr:\s*(\w+)", body)
        if mv:
            o["vrr"] = mv.group(1)
        modes, cur, pref = [], None, None
        for _id, w, h, r, star, bang in MODE_RE.findall(body.split("Custom modes")[0]):
            t = (int(w), int(h), float(r))
            modes.append(t)
            if star:
                cur = t
            if bang:
                pref = t
        _finish_modes(o, modes, cur, pref)
        outputs.append(o)
    return outputs


def parse_kscreen_json(text: str) -> list[dict] | None:
    """Parse `kscreen-doctor -j` (libkscreen ConfigSerializer). None when it is not that JSON."""
    try:
        doc = json.loads(text)
        raw = doc["outputs"]
        if not isinstance(raw, list):
            return None
        outputs = []
        for r in raw:
            o = _new_output(r.get("id"), r.get("name"))
            o.update(enabled=r.get("enabled"), connected=r.get("connected"), priority=r.get("priority"),
                     scale=float(r["scale"]) if r.get("scale") is not None else None,
                     hdr=r.get("hdr", False if "hdr" not in r else None), vrr=r.get("vrrPolicy"))
            if isinstance(r.get("pos"), dict):
                o["pos"] = [r["pos"].get("x"), r["pos"].get("y")]
            by_id, modes = {}, []
            for md in r.get("modes", []):
                t = (int(md["size"]["width"]), int(md["size"]["height"]), float(md["refreshRate"]))
                by_id[str(md["id"])] = t
                modes.append(t)
            prefs = [str(x) for x in r.get("preferredModes", [])]
            _finish_modes(o, modes, by_id.get(str(r.get("currentModeId"))),
                          by_id.get(prefs[0]) if prefs else None)
            outputs.append(o)
        return outputs
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def edid_name(edid: bytes) -> str | None:
    """Monitor name from the EDID base block (display descriptor tag 0xFC)."""
    if len(edid) < 128:
        return None
    for off in (54, 72, 90, 108):
        d = edid[off:off + 18]
        if d[0:3] == b"\0\0\0" and d[3] == 0xFC:
            return d[5:18].split(b"\n", 1)[0].decode("ascii", "replace").strip() or None
    return None


def drm_connectors(root: Path = Path("/sys/class/drm")) -> list[dict]:
    """Connected DRM connectors with their EDID monitor name and deduplicated mode sizes.

    The kernel lists the preferred mode first and one line per timing, so sizes repeat. Sizes above
    the preferred one are modes the monitor's scaler accepts (the LG 27GL850's EDID offers 3840x2160
    over HDMI), not its native resolution.
    """
    out = []
    if not Path(root).exists():
        return out
    for p in sorted(Path(root).glob("card*-*")):
        status = _read(str(p / "status"))
        if not status or status.strip() != "connected":
            continue
        sizes = []
        for m in (_read(str(p / "modes")) or "").split():
            if m not in sizes:
                sizes.append(m)
        pref = sizes[0] if sizes else None

        def area(m):
            mm = re.match(r"(\d+)x(\d+)", m)
            return int(mm.group(1)) * int(mm.group(2)) if mm else 0
        try:
            edid = (p / "edid").read_bytes()
        except OSError:
            edid = b""
        out.append({"connector": p.name.split("-", 1)[1], "monitor": edid_name(edid), "preferred": pref,
                    "modes": sizes, "above_preferred": [m for m in sizes if pref and area(m) > area(pref)]})
    return out


def display_info(kscreen_json: str | None = None, kscreen_text: str | None = None,
                 drm_root: Path = Path("/sys/class/drm")) -> dict:
    """Outputs from `kscreen-doctor -j` (preferred) or `-o` (fallback), plus the DRM connectors."""
    if kscreen_json is None and kscreen_text is None:
        kscreen_json = _run(["kscreen-doctor", "-j"])
    outputs, source = (parse_kscreen_json(kscreen_json) if kscreen_json else None), "kscreen-doctor -j"
    if not outputs:
        if kscreen_text is None:
            kscreen_text = _run(["kscreen-doctor", "-o"])
        outputs, source = (parse_kscreen(kscreen_text) if kscreen_text else []), "kscreen-doctor -o"
        if not outputs:
            source = None
    return {"outputs": outputs, "source": source, "drm_connected": drm_connectors(drm_root),
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
