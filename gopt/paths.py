"""Where the tool keeps its own files. GOPT_HOME redirects everything (used by tests)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


class Paths:
    def __init__(self, home: Path | None = None):
        self.home = Path(home or os.environ.get("GOPT_HOME") or Path.home())
        self.config_dir = self.home / ".config" / "game-optimiser"
        self.config_file = self.config_dir / "config.toml"
        self.cache_dir = self.home / ".cache" / "game-optimiser"
        self.hardware_cache = self.cache_dir / "hardware.json"
        self.data_dir = self.home / ".local" / "share" / "game-optimiser"
        self.runs = self.data_dir / "runs"
        self.mangohud_dir = self.home / ".config" / "MangoHud"

    def config(self) -> dict:
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "rb") as f:
                return tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    def allowed_write_roots(self, steam_root: Path) -> list[Path]:
        return [Path(steam_root), self.mangohud_dir, self.data_dir]
