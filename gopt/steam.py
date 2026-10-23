"""Steam on the host: root, libraries, app manifests, user id, launch options, running checks.

Read only except get_launch_options_text(), which returns new text for the
session to write through safety.write_file().
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from . import Refusal
from .parsers.keyvalues import KeyValues
from .safety import read_text_or_refuse

STEAMID64_BASE = 76561197960265728
DEFAULT_ROOT = Path.home() / ".local/share/Steam"
FLATPAK_ROOT = Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam"
LAUNCH_OPTIONS_PATH = ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps"]  # top key [U]


@dataclass
class InstalledApp:
    appid: int
    name: str
    installdir: str
    library: str
    size_bytes: int
    last_played: int
    last_updated: int
    buildid: str
    proton: bool
    install_path: str

    def as_dict(self):
        return asdict(self)


class Steam:
    def __init__(self, root: Path | None = None):
        env = os.environ.get("GOPT_STEAM_ROOT")
        self.root = Path(root or env or DEFAULT_ROOT)
        if not self.root.exists():
            if FLATPAK_ROOT.exists() and root is None and not env:
                raise Refusal(f"only the Flatpak Steam was found ({FLATPAK_ROOT}); v1 supports the host Steam at {DEFAULT_ROOT}")
            raise Refusal(f"Steam root not found: {self.root} (set GOPT_STEAM_ROOT)")

    # ---- libraries and apps -------------------------------------------
    def libraries(self) -> list[Path]:
        libs: list[Path] = []
        lf = self.root / "steamapps" / "libraryfolders.vdf"
        if lf.exists():
            kv = KeyValues(read_text_or_refuse(lf))
            top = kv.root()
            if top is not None:
                for child in top.children:
                    pnode = child.child("path")
                    if pnode is not None and pnode.value:
                        p = Path(pnode.value)
                        if p not in libs:
                            libs.append(p)
        if self.root not in libs and (self.root / "steamapps").exists():
            libs.insert(0, self.root)
        return libs

    def apps(self) -> list[InstalledApp]:
        out = []
        for lib in self.libraries():
            sa = lib / "steamapps"
            if not sa.is_dir():
                continue
            for mf in sorted(sa.glob("appmanifest_*.acf")):
                try:
                    kv = KeyValues(read_text_or_refuse(mf))
                except Refusal:
                    continue
                st = kv.root("AppState")
                if st is None:
                    continue
                g = lambda k, d="": (st.child(k).value if st.child(k) is not None and st.child(k).value is not None else d)
                try:
                    appid = int(g("appid", "0"))
                except ValueError:
                    continue
                installdir = g("installdir")
                out.append(InstalledApp(
                    appid=appid, name=g("name", f"app {appid}"), installdir=installdir, library=str(lib),
                    size_bytes=int(g("SizeOnDisk", "0") or 0), last_played=int(g("LastPlayed", "0") or 0),
                    last_updated=int(g("LastUpdated", "0") or 0), buildid=g("buildid"),
                    proton=(sa / "compatdata" / str(appid)).is_dir(),
                    install_path=str(sa / "common" / installdir)))
        out.sort(key=lambda a: a.name.lower())
        return out

    def app(self, appid: int) -> InstalledApp | None:
        for a in self.apps():
            if a.appid == appid:
                return a
        return None

    def compatdata(self, appid: int) -> Path | None:
        for lib in self.libraries():
            p = lib / "steamapps" / "compatdata" / str(appid)
            if p.is_dir():
                return p
        return None

    def proton_version(self, appid: int) -> str | None:
        cd = self.compatdata(appid)
        if cd is None:
            return None
        vf = cd / "version"
        if vf.exists():
            try:
                return vf.read_text(encoding="utf-8", errors="replace").strip() or None
            except OSError:
                return None
        return None

    # ---- user -----------------------------------------------------------
    def user_id(self) -> int:
        lu = self.root / "config" / "loginusers.vdf"
        if lu.exists():
            kv = KeyValues(read_text_or_refuse(lu))
            users = kv.root("users")
            best = None
            if users is not None:
                for u in users.children:
                    mr = u.child("MostRecent")
                    if mr is not None and mr.value == "1":
                        best = u
                        break
                if best is None and len(users.children) == 1:
                    best = users.children[0]
            if best is not None:
                try:
                    return int(best.key) - STEAMID64_BASE
                except ValueError:
                    pass
        ud = self.root / "userdata"
        if ud.is_dir():
            dirs = [d for d in ud.iterdir() if d.is_dir() and d.name.isdigit() and d.name != "0"]
            if len(dirs) == 1:
                return int(dirs[0].name)
        raise Refusal("could not determine the Steam user (loginusers.vdf has no MostRecent user and userdata is ambiguous)")

    def userdata(self) -> Path:
        p = self.root / "userdata" / str(self.user_id())
        if not p.is_dir():
            raise Refusal(f"userdata folder not found: {p}")
        return p

    def localconfig_path(self) -> Path:
        return self.userdata() / "config" / "localconfig.vdf"

    # ---- launch options -------------------------------------------------
    def get_launch_options(self, appid: int) -> str | None:
        kv = KeyValues(read_text_or_refuse(self.localconfig_path()))
        return kv.get(LAUNCH_OPTIONS_PATH + [str(appid), "LaunchOptions"])

    def launch_options_text(self, appid: int, new_value: str) -> tuple[str, str]:
        """(old_text, new_text) for localconfig.vdf with the app's LaunchOptions set."""
        text = read_text_or_refuse(self.localconfig_path())
        kv = KeyValues(text)
        if kv.find(LAUNCH_OPTIONS_PATH + [str(appid)]) is None:
            raise Refusal(f"app {appid} has no block in localconfig.vdf; start the game once from Steam first")
        new = kv.set(LAUNCH_OPTIONS_PATH + [str(appid), "LaunchOptions"], new_value)
        return text, new.text

    # ---- processes ------------------------------------------------------
    @staticmethod
    def running_processes(proc: Path = Path("/proc")) -> list[tuple[str, str]]:
        """[(comm, cmdline)] for every process we can read."""
        out = []
        try:
            entries = list(proc.iterdir())
        except OSError:
            return out
        for d in entries:
            if not d.name.isdigit():
                continue
            try:
                comm = (d / "comm").read_text(errors="replace").strip()
                cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            except OSError:
                continue
            out.append((comm, cmd))
        return out

    @staticmethod
    def any_running(names: list[str], processes: list[tuple[str, str]]) -> list[str]:
        """Names found among processes (comm or basename in cmdline, case insensitive)."""
        found = []
        for name in names:
            nl = name.lower()
            for comm, cmd in processes:
                if comm.lower() == nl[:15].lower() or re.search(r"(^|[\\/ ])" + re.escape(nl) + r"(\s|$)", cmd.lower()):
                    found.append(name)
                    break
        return found

    @staticmethod
    def steam_running(processes: list[tuple[str, str]]) -> bool:
        for comm, cmd in processes:
            if comm in ("steam", "steamwebhelper") or re.search(r"/ubuntu12_32/steam(\s|$)", cmd):
                return True
        return False


def rewrite_launch_options(current: str | None, remove_patterns: list[str], ensure_prefix: str | None,
                           ensure_args: list[str] | None = None) -> str:
    """Build the replacement launch option string.

    Removes any whitespace separated token group matching a remove pattern
    (for gamescope: everything up to and including the '--' before %command%),
    prepends ensure_prefix (e.g. 'mangohud') and appends ensure_args after %command%.
    """
    cur = (current or "").strip()
    if not cur:
        cur = "%command%"
    if "%command%" not in cur:
        cur = cur + " %command%"
    before, after = cur.split("%command%", 1)
    tokens = before.split()
    for pat in remove_patterns:
        if any(pat in t for t in tokens):
            # drop the wrapper and its flags: from the matching token to the end of 'before'
            idx = next(i for i, t in enumerate(tokens) if pat in t)
            tokens = tokens[:idx]
    tokens = [t for t in tokens if t != "--"]
    if ensure_prefix:
        ptoks = ensure_prefix.split()
        if not any(t == ptoks[-1] for t in tokens):
            tokens = tokens + ptoks
    after_tokens = after.split()
    for a in ensure_args or []:
        if a not in after_tokens:
            after_tokens.append(a)
    out = " ".join(tokens + ["%command%"] + after_tokens)
    return out.strip()
