"""Backups, manifest, verification, census, stale plan check and undo.

Every write in the tool goes through write_file(). Nothing here deletes.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from . import Refusal, __version__


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text_or_refuse(path: Path) -> str:
    """Read a config file; any problem is a hard stop, never an empty default."""
    path = Path(path)
    if not path.exists():
        raise Refusal(f"missing file: {path}")
    if not os.access(path, os.R_OK):
        raise Refusal(f"unreadable file (permissions): {path}")
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            data = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Refusal(f"unreadable file: {path}: {e}")
    if not data.strip():
        raise Refusal(f"empty file, refusing to treat as defaults: {path}")
    return data


def within_roots(path: Path, roots: list[Path]) -> bool:
    try:
        rp = Path(path).resolve()
    except OSError:
        return False
    for r in roots:
        try:
            rp.relative_to(Path(r).resolve())
            return True
        except ValueError:
            continue
    return False


@dataclass
class ManifestEntry:
    original: str
    backup: str
    size: int
    mtime: float
    sha256: str
    reason: str
    written_sha256: str | None = None
    restored: bool = False


class RunDir:
    """One tuning run's folder: plan, backups, logs, metrics, report."""

    def __init__(self, base: Path, run_id: str):
        self.base = Path(base)
        self.run_id = run_id
        self.path = self.base / run_id
        self.backups = self.path / "backups"
        self.logs = self.path / "logs"
        self.manifest_path = self.path / "MANIFEST.json"

    @staticmethod
    def new_id(game: str) -> str:
        return time.strftime("%Y%m%d-%H%M%S") + f"-{game}"

    def create(self):
        self.backups.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._save([])
        return self

    def _load(self) -> list[ManifestEntry]:
        if not self.manifest_path.exists():
            return []
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [ManifestEntry(**e) for e in raw.get("entries", [])]

    def _save(self, entries: list[ManifestEntry]):
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": __version__, "run_id": self.run_id,
                       "entries": [asdict(e) for e in entries]}, f, indent=2)
        os.replace(tmp, self.manifest_path)

    def entries(self) -> list[ManifestEntry]:
        return self._load()

    def backup(self, path: Path, reason: str) -> ManifestEntry:
        """Copy a file into the run's backup folder and record it. Verified by sha256."""
        path = Path(path)
        if not path.exists():
            raise Refusal(f"cannot back up a missing file: {path}")
        entries = self._load()
        for e in entries:
            if e.original == str(path) and not e.restored:
                return e   # already backed up in this run: keep the first original
        digest = sha256_of(path)
        dest = self.backups / f"{digest[:12]}_{path.name}"
        shutil.copy2(path, dest)
        if sha256_of(dest) != digest:
            raise Refusal(f"backup verification failed for {path}")
        st = path.stat()
        entry = ManifestEntry(original=str(path), backup=str(dest), size=st.st_size,
                              mtime=st.st_mtime, sha256=digest, reason=reason)
        entries.append(entry)
        self._save(entries)
        return entry

    def record_write(self, path: Path, written_sha: str):
        entries = self._load()
        for e in entries:
            if e.original == str(path):
                e.written_sha256 = written_sha
        self._save(entries)

    def undo(self, force: bool = False) -> list[str]:
        """Restore every backed up file once, in reverse order. Returns restored paths."""
        entries = self._load()
        if not entries:
            raise Refusal("nothing to undo in this run")
        if all(e.restored for e in entries):
            raise Refusal("this run was already undone; a second undo is refused")
        restored = []
        for e in reversed(entries):
            if e.restored:
                continue
            orig = Path(e.original)
            if orig.exists():
                cur = sha256_of(orig)
                if cur not in (e.sha256, e.written_sha256) and not force:
                    raise Refusal(
                        f"{orig} was changed by something else since this run "
                        f"(sha {cur[:12]}); use --force to overwrite it anyway")
            shutil.copy2(e.backup, orig)
            if sha256_of(orig) != e.sha256:
                raise Refusal(f"restore verification failed for {orig}")
            e.restored = True
            restored.append(str(orig))
        self._save(entries)
        return restored


def census(paths: list[Path]) -> tuple[int, int]:
    """(count, total bytes) of the files that exist among paths."""
    count = total = 0
    for p in paths:
        p = Path(p)
        if p.exists():
            count += 1
            total += p.stat().st_size
    return count, total


def write_file(run: RunDir, path: Path, new_text: str, reason: str,
               allowed_roots: list[Path], census_paths: list[Path] | None = None,
               min_ratio: float = 0.5) -> str:
    """Back up, write atomically, verify. Returns the sha256 of what was written.

    Refuses when the path is outside allowed_roots, when the new text is empty,
    or when the write would shrink the file below min_ratio of its size
    (a config file that loses half its content is almost always a bug).
    """
    path = Path(path)
    if not within_roots(path, allowed_roots):
        raise Refusal(f"refusing to write outside the allowed roots: {path}")
    if not new_text.strip():
        raise Refusal(f"refusing to write an empty file: {path}")
    data = new_text.encode("utf-8")
    before_count, before_bytes = census(census_paths or [path])
    if path.exists():
        run.backup(path, reason)
        old_size = path.stat().st_size
        if old_size and len(data) < old_size * min_ratio:
            raise Refusal(f"refusing: new content is {len(data)} bytes, old was {old_size}: {path}")
    tmp = path.with_name(path.name + ".gopt-tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    shutil.copystat(path, tmp) if path.exists() else None
    os.replace(tmp, path)
    digest = sha256_of(path)
    if digest != sha256_bytes(data):
        raise Refusal(f"write verification failed for {path}")
    after_count, after_bytes = census(census_paths or [path])
    if after_count < before_count:
        raise Refusal(f"census: file count fell from {before_count} to {after_count}")
    run.record_write(path, digest)
    return digest


def file_fingerprints(paths: list[Path]) -> dict[str, str]:
    return {str(p): sha256_of(Path(p)) for p in paths if Path(p).exists()}


def check_not_stale(expected: dict[str, str]):
    """Refuse when any planned target changed since the plan was made."""
    for p, sha in expected.items():
        pp = Path(p)
        if not pp.exists():
            raise Refusal(f"stale plan: {p} no longer exists")
        if sha256_of(pp) != sha:
            raise Refusal(f"stale plan: {p} changed since the plan was made; re-run plan")
