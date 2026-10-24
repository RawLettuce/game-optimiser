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
from ..parsers.jsontext import JsonText, JsonTextError
from ..parsers.srccfg import SrcCfg, SrcCfgError
from ..parsers.winreg import WinReg, WinRegError

PARSE_ERRORS = (EECfgError, KeyValuesError, JsonTextError, SrcCfgError, WinRegError)
FORMATS = ("eecfg", "keyvalues", "ini", "srccfg", "json", "winreg")
from ..safety import read_text_or_refuse

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "adapters"


def data_dir() -> Path:
    """Adapter data folder; GOPT_ADAPTER_DIR overrides it (tests, or a user copy)."""
    import os
    return Path(os.environ.get("GOPT_ADAPTER_DIR") or DATA_DIR)


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
    fallback: str | None = None      # upscaling only: the level tried when native cannot reach the goal
    guess: bool = False              # key name or a level value not from any source: kept out of the ladder until discover verifies it
    # companion keys written with the main key, one value per level ("" leaves that key as it is at that level);
    # Warframe: UpscaleMethod is the main key, UpscaleQuality its companion (EE.cfg on the PC, 23 Oct 2026)
    extra_keys: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self):
        for k, vals in self.extra_keys.items():
            if len(vals) != len(self.levels):
                raise ValueError(f"setting {self.id}: extra key {k} has {len(vals)} values for {len(self.levels)} levels")

    @property
    def usable(self) -> bool:
        return not (self.guess and self.status != "V")

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

    def keys(self) -> list[str]:
        return [self.key] + list(self.extra_keys)

    def level_from(self, values: dict[str, str | None]) -> int | None:
        """Level from the main key, then checked against the companion keys that level sets
        (Warframe UM_DLSS with UQ_PERFORMANCE is not 'DLSS Quality': unrecognised, not a guess)."""
        lv = self.level_of(values.get(self.key))
        if lv is None:
            return None
        for k, vals in self.extra_keys.items():
            want = vals[lv]
            if want and (values.get(k) or "").strip().lower() != want.lower():
                return None
        return lv

    def values_for(self, lv: int) -> dict[str, str]:
        """Key -> value written for a level (companions with "" are left alone)."""
        out = {self.key: self.levels[lv]}
        out.update({k: vals[lv] for k, vals in self.extra_keys.items() if vals[lv]})
        return out


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
    settings_path_template: str | None
    settings_format: str | None
    keyroot: str | None
    launch_remove: list[str]
    launch_prefix: str | None
    launch_args: list[str]
    launch_forbid: list[str]
    launch_advice: list[str]
    overrides: list[Override]
    settings: list[Setting]
    benchmark: dict
    learned: dict = field(default_factory=dict)
    source: str = ""
    create_if_missing: bool = False
    settings_note: str = ""
    info_keys: list[dict] = field(default_factory=list)   # shown by `gopt show`, never written

    # ---- loading ----------------------------------------------------
    @classmethod
    def load(cls, game: str, data_dir_override: Path | None = None) -> "Adapter":
        path = Path(data_dir_override or data_dir()) / f"{game}.toml"
        if not path.exists():
            raise Refusal(f"no adapter for {game!r} (looked for {path}); `gopt library` lists installed games")
        with open(path, "rb") as f:
            d = tomllib.load(f)
        g = d["game"]
        fs = d.get("files", {}).get("settings", {})
        if fs.get("format") and fs["format"] not in FORMATS:
            raise Refusal(f"{path}: unknown settings format {fs['format']!r}")
        lo = d.get("launch_options", {})
        try:
            settings = [Setting(**{k: v for k, v in s.items()}) for s in d.get("settings", [])]
        except (TypeError, ValueError) as e:
            raise Refusal(f"{path}: {e}")
        overrides = [Override(**o) for o in d.get("run_overrides", [])]
        ad = cls(id=g["id"], name=g["name"], appid=int(g["appid"]), runtime=g["runtime"], program=g["program"],
                 processes=list(g.get("processes", [])), headroom=float(g.get("headroom", 1.0)),
                 settings_path_template=fs.get("path") or None, settings_format=fs.get("format"), keyroot=fs.get("keyroot"),
                 launch_remove=list(lo.get("remove_patterns", [])), launch_prefix=lo.get("ensure_prefix"),
                 launch_args=list(lo.get("ensure_args", [])), launch_forbid=list(lo.get("forbid", [])),
                 launch_advice=list(lo.get("advice", [])), overrides=overrides, settings=settings, benchmark=d.get("benchmark", {}), source=str(path),
                 create_if_missing=bool(fs.get("create_if_missing", False)), settings_note=fs.get("note", ""),
                 info_keys=list(d.get("info_keys", [])))
        learned_path = path.with_suffix(".learned.json")
        if learned_path.exists():
            try:
                ad.learned = json.loads(learned_path.read_text())
            except (OSError, ValueError) as e:
                raise Refusal(f"unreadable learned file {learned_path}: {e}")
            ad._apply_learned()
        return ad

    @staticmethod
    def available(data_dir_override: Path | None = None) -> list[str]:
        return sorted(p.stem for p in Path(data_dir_override or data_dir()).glob("*.toml"))

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
    @property
    def has_settings_file(self) -> bool:
        return bool(self.settings_path_template)

    def settings_path(self, steam) -> Path:
        tpl = self.settings_path_template
        if not tpl:
            raise Refusal(f"{self.name}: the settings file is not known yet ({self.settings_note or 'see ADAPTERS-RESEARCH.md'}); "
                          f"run `python3 -m gopt find-settings {self.id}` on the PC to locate it")
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
        if "{install}" in tpl:
            app = steam.app(self.appid)
            if app is None:
                raise Refusal(f"{self.name} (app {self.appid}) is not installed")
            values["install"] = app.install_path
        p = Path(tpl.format(**values))
        if any(ch in str(p) for ch in "*?["):
            hits = sorted(Path(p.anchor).glob(str(p.relative_to(p.anchor))))
            if len(hits) != 1:
                raise Refusal(f"{self.name}: settings path pattern {p} matched {len(hits)} files "
                              f"({', '.join(map(str, hits[:4]))}); expected exactly one")
            p = hits[0]
        return p

    # ---- settings file ------------------------------------------------
    def read_settings(self, path: Path | None) -> dict[str, str | None]:
        """Current value of every adapter setting and override key (None when absent, or when the
        file does not exist yet and the adapter creates it on the first write)."""
        if path is None or (self.create_if_missing and not Path(path).exists()):
            return {k: None for k in [k for s in self.settings for k in s.keys()] + [o.key for o in self.overrides]}
        doc = self.load_doc(path)
        out = {}
        for s in self.settings:
            for k in s.keys():
                out[k] = self._get(doc, k)
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
            if self.settings_format == "ini":
                return EECfg(text)
            if self.settings_format == "srccfg":
                return SrcCfg(text)
            if self.settings_format == "json":
                return JsonText(text)
            if self.settings_format == "winreg":
                return WinReg(text)
        except PARSE_ERRORS as e:
            raise Refusal(f"cannot parse {path}: {e}")
        raise Refusal(f"unknown settings format {self.settings_format}")

    def _get(self, doc, key: str):
        if self.settings_format == "ini":
            sec, k = key.rsplit("::", 1)
            return doc.get(k, section=sec)
        if self.settings_format == "keyvalues":
            return doc.get([self.keyroot, key]) if self.keyroot else doc.get([key])
        return doc.get(key)

    def doc_text(self, doc) -> str:
        return doc.text if self.settings_format == "keyvalues" else doc.text()

    def flat(self, doc) -> dict[str, str]:
        """Every key in the document (used to prove a write changed only the planned keys)."""
        if self.settings_format == "keyvalues":
            out = {}

            def walk(node, prefix):
                for k, v in node.items():
                    if isinstance(v, dict):
                        walk(v, f"{prefix}{k}/")
                    else:
                        out[f"{prefix}{k}"] = v
            walk(doc.to_obj(), "")
            return out
        return doc.flat()

    def apply_changes(self, doc, changes: dict[str, str]):
        """Return a new document with the given key -> value changes."""
        for key, value in changes.items():
            try:
                if self.settings_format == "keyvalues":
                    doc = doc.set([self.keyroot, key] if self.keyroot else [key], value)
                elif self.settings_format == "ini":
                    sec, k = key.rsplit("::", 1)
                    doc = doc.set(k, value, section=sec)
                else:
                    doc = doc.set(key, value)
            except PARSE_ERRORS as e:
                raise Refusal(f"cannot set {key}: {e}")
        return doc

    def current_levels(self, values: dict[str, str | None]) -> dict[str, int | None]:
        return {s.id: s.level_from(values) for s in self.settings}

    def changes_for_rung(self, rung: dict[str, int], current: dict[str, str | None]) -> dict[str, str]:
        """Key -> value edits needed to reach a rung from the current file (unchanged keys omitted)."""
        out = {}
        for s in self.settings:
            if s.id not in rung:
                continue
            for key, want in s.values_for(rung[s.id]).items():
                cur = current.get(key)
                if cur is None or cur.strip().lower() != want.lower():
                    out[key] = want
        return out

    def needs_discover(self, s: Setting, values: dict[str, str | None], path: Path | None) -> bool:
        """True when a setting must wait for `gopt discover`: a guessed key, or a key the settings file
        does not contain yet and no discover run has verified. Warframe writes most Graphics keys to
        EE.cfg only once they are changed in game (seen on the PC, 23 Oct 2026). Adapters that create
        their file (Garry's Mod autoexec.cfg) are exempt: every key starts absent there by design."""
        if not s.usable:
            return True
        if s.status == "V" or path is None or self.create_if_missing:
            return False
        return any(values.get(k) is None for k in s.keys())

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
