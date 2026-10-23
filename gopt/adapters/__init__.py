"""Game adapters loaded from data/adapters/<game>.toml plus <game>.learned.json.

Both first games use the same generic adapter; what differs is data (file
format, keys, levels, costs). A new game is a new TOML file.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .. import Refusal
from ..parsers.eecfg import EECfg, EECfgError
from ..parsers.keyvalues import KeyValues, KeyValuesError
from ..safety import read_text_or_refuse

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "adapters"


@dataclass
class Setting:
    id: str
    label: str
    key: str
    levels: list[str]
    labels: list[str]
    cost: list[float]
    cpu: bool = False
    visual: int = 3
    upscaling: bool = False
    status: str = "U"
    vram_mb: list[int] | None = None

    @property
    def top(self) -> int:
        return len(self.levels) - 1

    def level_of(self, value: str | None) -> int | None:
        if value is None:
            return None
        v = value.strip()
        for i, lv in enumerate(self.levels):
            if lv.lower() == v.lower():
                return i
        return None


@dataclass
class Override:
    key: str
    value: str
    status: str = "U"
    why: str = ""
    manual: str | None = None
    restore: bool = True


@dataclass
class Adapter:
    id: str
    name: str
    appid: int
    runtime: str
    program: str
    processes: list[str]
    headroom: float
    settings_path_template: str
    settings_format: str
    keyroot: str | None
    launch_remove: list[str]
    launch_prefix: str | None
    launch_args: list[str]
    launch_forbid: list[str]
    overrides: list[Override]
    settings: list[Setting]
    benchmark: dict
    learned: dict = field(default_factory=dict)
    source: str = ""

    # ---- loading ----------------------------------------------------
    @classmethod
    def load(cls, game: str, data_dir: Path = DATA_DIR) -> "Adapter":
        path = Path(data_dir) / f"{game}.toml"
        if not path.exists():
            raise Refusal(f"no adapter for {game!r} (looked for {path}); `gopt library` lists installed games")
        with open(path, "rb") as f:
            d = tomllib.load(f)
        g = d["game"]
        fs = d["files"]["settings"]
        lo = d.get("launch_options", {})
        settings = [Setting(**{k: v for k, v in s.items()}) for s in d.get("settings", [])]
        overrides = [Override(**o) for o in d.get("run_overrides", [])]
        ad = cls(id=g["id"], name=g["name"], appid=int(g["appid"]), runtime=g["runtime"], program=g["program"],
                 processes=list(g.get("processes", [])), headroom=float(g.get("headroom", 1.0)),
                 settings_path_template=fs["path"], settings_format=fs["format"], keyroot=fs.get("keyroot"),
                 launch_remove=list(lo.get("remove_patterns", [])), launch_prefix=lo.get("ensure_prefix"),
                 launch_args=list(lo.get("ensure_args", [])), launch_forbid=list(lo.get("forbid", [])),
                 overrides=overrides, settings=settings, benchmark=d.get("benchmark", {}), source=str(path))
        learned_path = path.with_suffix(".learned.json")
        if learned_path.exists():
            try:
                ad.learned = json.loads(learned_path.read_text())
            except (OSError, ValueError) as e:
                raise Refusal(f"unreadable learned file {learned_path}: {e}")
            ad._apply_learned()
        return ad

    @staticmethod
    def available(data_dir: Path = DATA_DIR) -> list[str]:
        return sorted(p.stem for p in Path(data_dir).glob("*.toml"))

    def learned_path(self) -> Path:
        return Path(self.source).with_suffix(".learned.json")

    def _apply_learned(self):
        keys = self.learned.get("keys", {})
        for s in self.settings:
            k = keys.get(s.id)
            if not k:
                continue
            if k.get("key"):
                s.key = k["key"]
            if k.get("levels") and len(k["levels"]) == len(s.levels):
                s.levels = list(k["levels"])
            s.status = k.get("status", "V")
        costs = self.learned.get("costs", {})
        for s in self.settings:
            c = costs.get(s.id)
            if c and len(c) == len(s.cost):
                s.cost = [float(x) for x in c]
        if "headroom" in self.learned:
            self.headroom = float(self.learned["headroom"])
        okeys = self.learned.get("override_keys", {})
        for o in self.overrides:
            if o.key in okeys:
                o.key, o.status = okeys[o.key], "V"

    def save_learned(self, data: dict):
        self.learned = data
        self.learned_path().write_text(json.dumps(data, indent=2, sort_keys=True))

    # ---- paths --------------------------------------------------------
    def settings_path(self, steam) -> Path:
        tpl = self.settings_path_template
        values = {}
        if "{compatdata}" in tpl:
            cd = steam.compatdata(self.appid)
            if cd is None:
                raise Refusal(f"{self.name}: no Proton prefix (compatdata/{self.appid}) found; run the game once first")
            values["compatdata"] = str(cd)
        if "{userdata}" in tpl:
            values["userdata"] = str(steam.userdata())
        if "{steam}" in tpl:
            values["steam"] = str(steam.root)
        return Path(tpl.format(**values))

    # ---- settings file ------------------------------------------------
    def read_settings(self, path: Path) -> dict[str, str | None]:
        """Current value of every adapter setting and override key (None when absent)."""
        doc = self.load_doc(path)
        out = {}
        for s in self.settings:
            out[s.key] = self._get(doc, s.key)
        for o in self.overrides:
            out[o.key] = self._get(doc, o.key)
        return out

    def load_doc(self, path: Path):
        text = read_text_or_refuse(path)
        try:
            if self.settings_format == "eecfg":
                return EECfg(text)
            if self.settings_format == "keyvalues":
                return KeyValues(text)
        except (EECfgError, KeyValuesError) as e:
            raise Refusal(f"cannot parse {path}: {e}")
        raise Refusal(f"unknown settings format {self.settings_format}")

    def _get(self, doc, key: str):
        if self.settings_format == "eecfg":
            return doc.get(key)
        return doc.get([self.keyroot, key]) if self.keyroot else doc.get([key])

    def doc_text(self, doc) -> str:
        return doc.text() if self.settings_format == "eecfg" else doc.text

    def apply_changes(self, doc, changes: dict[str, str]):
        """Return a new document with the given key -> value changes."""
        for key, value in changes.items():
            try:
                if self.settings_format == "eecfg":
                    doc = doc.set(key, value)
                else:
                    doc = doc.set([self.keyroot, key] if self.keyroot else [key], value)
            except (EECfgError, KeyValuesError) as e:
                raise Refusal(f"cannot set {key}: {e}")
        return doc

    def current_levels(self, values: dict[str, str | None]) -> dict[str, int | None]:
        return {s.id: s.level_of(values.get(s.key)) for s in self.settings}

    def changes_for_rung(self, rung: dict[str, int], current: dict[str, str | None]) -> dict[str, str]:
        """Key -> value edits needed to reach a rung from the current file (unchanged keys omitted)."""
        out = {}
        for s in self.settings:
            if s.id not in rung:
                continue
            want = s.levels[rung[s.id]]
            cur = current.get(s.key)
            if cur is None or cur.strip().lower() != want.lower():
                out[s.key] = want
        return out

    def override_changes(self, current: dict[str, str | None]) -> tuple[dict[str, str], list[Override]]:
        """(automatic key edits, overrides that must be done by hand because their key is unverified)."""
        auto, manual = {}, []
        for o in self.overrides:
            if o.status == "U" and o.manual:
                manual.append(o)
                continue
            if (current.get(o.key) or "").strip() != o.value:
                auto[o.key] = o.value
        return auto, manual

    def setting(self, sid: str) -> Setting:
        for s in self.settings:
            if s.id == sid:
                return s
        raise KeyError(sid)
