"""MangoHud: per application config text, log discovery and CSV parsing.

Facts from the MangoHud README and src/logging.cpp (see DESIGN.md section 9).
"""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from . import Refusal

FRAME_COLUMNS_MIN = {"fps", "frametime"}


def config_text(output_folder: Path, log_duration_s: int, log_interval_ms: int = 50,
                autostart_s: int = 0, no_display: bool = True, fps_limit: int = 0) -> str:
    lines = [
        "# written by game-optimiser; restored from backup at the end of the session",
        f"output_folder={output_folder}",
        f"log_duration={log_duration_s}",
        f"autostart_log={autostart_s}",
        f"log_interval={log_interval_ms}",
        "toggle_logging=Shift_L+F2",
        "benchmark_percentiles=97,AVG,1,0.1",
        "log_versioning",
        f"fps_limit={fps_limit}",
    ]
    if no_display:
        lines.append("no_display")
    return "\n".join(lines) + "\n"


def app_config_path(mangohud_dir: Path, program: str, proton: bool) -> Path:
    """~/.config/MangoHud/<app>.conf or wine-<app>.conf (README)."""
    stem = Path(program).stem if program.lower().endswith(".exe") else program
    name = f"wine-{stem}.conf" if proton else f"{stem}.conf"
    return Path(mangohud_dir) / name


def parse_log(path: Path) -> dict:
    """Parse a MangoHud CSV (with or without log_versioning headers).

    Returns {"sysinfo": {...}, "columns": [...], "rows": [{col: float|str}]}.
    The frame table starts at the first line whose first field is 'fps'.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise Refusal(f"cannot read MangoHud log {path}: {e}")
    lines = text.splitlines()
    sysinfo = {}
    frame_start = None
    for i, line in enumerate(lines):
        first = line.split(",", 1)[0].strip().lower()
        if first == "os" and i + 1 < len(lines):
            keys = [k.strip() for k in line.split(",")]
            vals = next(csv.reader([lines[i + 1]]))
            sysinfo = dict(zip(keys, vals))
        if first == "fps":
            frame_start = i
            break
    if frame_start is None:
        raise Refusal(f"no frame table (a line starting with 'fps,') in {path}")
    reader = csv.reader(io.StringIO("\n".join(lines[frame_start:])))
    columns = [c.strip() for c in next(reader)]
    if not FRAME_COLUMNS_MIN <= set(columns):
        raise Refusal(f"unexpected MangoHud columns in {path}: {columns}")
    rows = []
    for rec in reader:
        if not rec or len(rec) < 2:
            continue
        row = {}
        for c, v in zip(columns, rec):
            try:
                row[c] = float(v)
            except ValueError:
                row[c] = v
        if isinstance(row.get("frametime"), float) and row["frametime"] > 0:
            rows.append(row)
    if len(rows) < 10:
        raise Refusal(f"MangoHud log {path} has only {len(rows)} usable frames")
    return {"sysinfo": sysinfo, "columns": columns, "rows": rows}


def find_logs(folder: Path, program_hint: str | None = None, since: float = 0.0) -> list[Path]:
    """CSV logs in folder (not summaries), newest first, optionally filtered by program name."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    for p in folder.glob("*.csv"):
        if p.name.endswith("_summary.csv"):
            continue
        try:
            if p.stat().st_mtime < since:
                continue
        except OSError:
            continue
        if program_hint and not p.name.lower().startswith(Path(program_hint).stem.lower()):
            continue
        out.append(p)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def pick_log(candidates: list[Path]) -> Path | None:
    """The candidate with the most frame rows (the game, not its launcher)."""
    best, best_rows = None, -1
    for p in candidates:
        try:
            n = sum(1 for _ in open(p, "rb"))
        except OSError:
            continue
        if n > best_rows:
            best, best_rows = p, n
    return best


def wait_for_log(folder: Path, program_hint: str | None, since: float, quiet_s: float = 15.0,
                 timeout_s: float = 900.0, poll_s: float = 1.0, sleep=time.sleep, clock=time.time) -> Path:
    """Wait until a new log appears and stops growing for quiet_s seconds."""
    start = clock()
    last_size, last_change = -1, clock()
    chosen = None
    while clock() - start < timeout_s:
        logs = find_logs(folder, program_hint, since)
        if logs:
            chosen = pick_log(logs)
            size = chosen.stat().st_size
            if size != last_size:
                last_size, last_change = size, clock()
            elif clock() - last_change >= quiet_s and size > 0:
                return chosen
        sleep(poll_s)
    if chosen is not None:
        return chosen
    raise Refusal(f"no MangoHud log appeared in {folder} within {int(timeout_s)} s")
