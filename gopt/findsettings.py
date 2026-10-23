"""Find where a game keeps a setting: snapshot its likely config folders, let Matthew change one
option in game, snapshot again, and show which file and which lines changed.

Read only. Used to fill the [U] settings files of new adapters on the PC (Risk of Rain Returns,
Brotato, Bloons TD 6). Works for any installed appid, adapter or not.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path

MAX_SIZE = 4 * 1024 * 1024          # bigger files are hashed by size and mtime only
MAX_TEXT = 512 * 1024               # smaller text files keep their content for the line diff
MAX_REG = 32 * 1024 * 1024          # a prefix's user.reg is kept in full
MAX_FILES = 30000
SKIP_DIRS = ("cache", "shader", "logs", "crash", "temp", "dxvk", "vkd3d", "nvidia", "microsoft", "steamworks")


def roots_for(steam, appid: int) -> list[Path]:
    """Likely config locations for an installed app: the Proton prefix's user folders and user.reg,
    the install folder and Steam's userdata/<user>/<appid>."""
    roots = []
    cd = steam.compatdata(appid)
    if cd is not None:
        user = cd / "pfx" / "drive_c" / "users" / "steamuser"
        for sub in ("AppData/Local", "AppData/LocalLow", "AppData/Roaming", "Documents"):
            roots.append(user / sub)
        roots.append(cd / "pfx" / "user.reg")
    app = steam.app(appid)
    if app is not None:
        roots.append(Path(app.install_path))
    try:
        roots.append(steam.userdata() / str(appid))
    except Exception:
        pass
    return [r for r in roots if r.exists()]


def _is_text(data: bytes) -> bool:
    if b"\0" in data[:4096]:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def snapshot(roots: list[Path]) -> dict:
    """{path: {"size", "mtime", "sha", "text"}} for files under the roots, bounded."""
    out = {}
    count = 0

    def add(p: Path):
        nonlocal count
        count += 1
        try:
            st = p.stat()
        except OSError:
            return
        limit = MAX_REG if p.name == "user.reg" else MAX_SIZE
        rec = {"size": st.st_size, "mtime": int(st.st_mtime), "sha": None, "text": None}
        if st.st_size <= limit:
            try:
                data = p.read_bytes()
            except OSError:
                return
            rec["sha"] = hashlib.sha256(data).hexdigest()
            if (st.st_size <= MAX_TEXT or p.name == "user.reg") and _is_text(data):
                rec["text"] = data.decode("utf-8")
        out[str(p)] = rec

    for root in roots:
        if root.is_file():
            add(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not any(s in d.lower() for s in SKIP_DIRS)]
            for f in filenames:
                if count >= MAX_FILES:
                    return out
                add(Path(dirpath) / f)
    return out


def diff(before: dict, after: dict, max_lines: int = 20) -> list[dict]:
    """Changed, added and removed files with the changed lines of text files."""
    res = []
    for p in sorted(set(before) | set(after)):
        a, b = before.get(p), after.get(p)
        if a and b and a["size"] == b["size"] and a["sha"] == b["sha"] and (a["sha"] or a["mtime"] == b["mtime"]):
            continue
        kind = "added" if a is None else "removed" if b is None else "changed"
        lines = []
        if kind == "changed" and a.get("text") is not None and b.get("text") is not None:
            for ln in difflib.unified_diff(a["text"].splitlines(), b["text"].splitlines(), lineterm="", n=0):
                if ln.startswith(("---", "+++", "@@")):
                    continue
                lines.append(ln)
                if len(lines) >= max_lines:
                    lines.append("...")
                    break
        res.append({"path": p, "kind": kind, "lines": lines})
    return res


def save(snap: dict, path: Path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(snap))


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())
