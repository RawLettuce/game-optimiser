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
    runtime: str = "unknown"          # native, proton, proton? (compatdata only) or unknown
    runtime_source: str = ""
    compat_tool: str | None = None

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
        """Library folders, each listed once. Paths are compared by realpath and inode: on Bazzite
        /home and /var/home may be a symlink or a bind mount, so the Steam root (/home/...) and
        libraryfolders.vdf (/var/home/...) name the same folder (seen on the PC, 23-24 Oct 2026)."""
        libs: list[Path] = []
        seen: set[object] = set()

        def add(p: Path, first: bool = False):
            real = os.path.realpath(p)
            try:
                st = os.stat(real)
                key: object = (st.st_dev, st.st_ino) if st.st_ino else real
            except OSError:
                key = real
            if real in seen or key in seen:
                return
            seen.add(real)
            seen.add(key)
            libs.insert(0, p) if first else libs.append(p)

        if (self.root / "steamapps").exists():
            add(self.root, first=True)
        lf = self.root / "steamapps" / "libraryfolders.vdf"
        if lf.exists():
            kv = KeyValues(read_text_or_refuse(lf))
            top = kv.root()
            if top is not None:
                for child in top.children:
                    pnode = child.child("path")
                    if pnode is not None and pnode.value:
                        add(Path(pnode.value))
        return libs

    # ---- runtime: native Linux or Proton ------------------------------
    def compat_tool_mapping(self) -> dict[str, str]:
        """appid -> compatibility tool name from config/config.vdf CompatToolMapping (the per game
        'Force the use of a specific Steam Play compatibility tool' choice; "0" is the global default,
        which Steam applies only to games without a Linux build). Same lookup as protontricks [P]."""
        cfg = self.root / "config" / "config.vdf"
        if not cfg.exists():
            return {}
        try:
            kv = KeyValues(read_text_or_refuse(cfg))
        except Exception:
            return {}
        node = kv.find(["InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping"])
        out = {}
        for c in (node.children if node is not None else []):
            n = c.child("name")
            if n is not None and n.value:
                out[c.key] = n.value
        return out

    @staticmethod
    def scan_binaries(install: Path, max_depth: int = 5, max_entries: int = 4000) -> tuple[str | None, str | None]:
        """(first Linux ELF executable, first Windows .exe) under an install folder, bounded.
        Shared libraries (.so) are ignored: Windows games ship Linux EasyAntiCheat libraries."""
        elf = exe = None
        seen = 0
        stack = [(Path(install), 0)]
        while stack and seen < max_entries:
            d, depth = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                seen += 1
                if seen > max_entries:
                    break
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth + 1 < max_depth:
                            stack.append((Path(e.path), depth + 1))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    low = e.name.lower()
                    if low.endswith(".exe"):
                        exe = exe or e.path
                        continue
                    if ".so" in low or not (e.stat(follow_symlinks=False).st_mode & 0o111):
                        continue
                    with open(e.path, "rb") as f:
                        if f.read(4) == b"\x7fELF":
                            return e.path, exe
                except OSError:
                    continue
        return elf, exe

    def detect_runtime(self, appid: int, install: Path, compatdata_exists: bool,
                       mapping: dict[str, str] | None = None) -> tuple[str, str, str | None]:
        """(runtime, why, compat tool). A compatdata folder alone is weak evidence: Steam leaves it
        behind for native games too (CS2 showed 'proton' on the PC, 23 Oct 2026)."""
        mapping = self.compat_tool_mapping() if mapping is None else mapping
        tool = mapping.get(str(appid))
        if tool:
            if tool.lower().startswith("steamlinuxruntime"):
                return "native", f"CompatToolMapping {tool}", tool
            return "proton", f"CompatToolMapping {tool}", tool
        elf, exe = self.scan_binaries(install) if install.is_dir() else (None, None)
        if elf:
            return "native", f"Linux ELF executable {Path(elf).relative_to(install)}", None
        if exe:
            return "proton", f"Windows .exe {Path(exe).relative_to(install)} and no Linux executable", mapping.get("0")
        if compatdata_exists:
            return "proton?", "only a compatdata folder (no executables found to check)", None
        return "unknown", "no executables found and no compatdata", None

    def apps(self) -> list[InstalledApp]:
        """Installed apps, read once per Steam object (the runtime check walks install folders)."""
        if getattr(self, "_apps", None) is None:
            self._apps = self._read_apps()
        return list(self._apps)

    def _read_apps(self) -> list[InstalledApp]:
        out = []
        seen: set[int] = set()
        mapping = self.compat_tool_mapping()
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
                if appid in seen:
                    continue
                seen.add(appid)
                installdir = g("installdir")
                install = sa / "common" / installdir
                runtime, why, tool = self.detect_runtime(appid, install, (sa / "compatdata" / str(appid)).is_dir(), mapping)
                out.append(InstalledApp(
                    appid=appid, name=g("name", f"app {appid}"), installdir=installdir, library=str(lib),
                    size_bytes=int(g("SizeOnDisk", "0") or 0), last_played=int(g("LastPlayed", "0") or 0),
                    last_updated=int(g("LastUpdated", "0") or 0), buildid=g("buildid"),
                    proton=runtime.startswith("proton"), install_path=str(install),
                    runtime=runtime, runtime_source=why, compat_tool=tool))
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

    def compat_tools(self) -> dict[str, list[str]]:
        """Installed Proton builds: Valve's under steamapps/common ("Proton - Experimental", "Proton 9.0")
        and custom ones (GE-Proton) under compatibilitytools.d. On the PC, 23 Oct 2026: Valve's
        Experimental and the EasyAntiCheat runtime only, compatibilitytools.d empty."""
        valve: list[str] = []
        for lib in self.libraries():
            common = lib / "steamapps" / "common"
            if common.is_dir():
                valve += sorted(d.name for d in common.iterdir() if d.is_dir() and d.name.lower().startswith("proton"))
        ctd = self.root / "compatibilitytools.d"
        custom = sorted(d.name for d in ctd.iterdir() if d.is_dir()) if ctd.is_dir() else []
        return {"valve": valve, "custom": custom}

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
    def _localconfig_text(self) -> str:
        return read_text_or_refuse(self.localconfig_path(), errors="surrogateescape")

    def get_launch_options(self, appid: int) -> str | None:
        kv = KeyValues(self._localconfig_text())
        return kv.get(LAUNCH_OPTIONS_PATH + [str(appid), "LaunchOptions"])

    def launch_options_text(self, appid: int, new_value: str) -> tuple[str, str]:
        """(old_text, new_text) for localconfig.vdf with the app's LaunchOptions set."""
        text = self._localconfig_text()
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
        me = str(os.getpid())
        for d in entries:
            if not d.name.isdigit() or d.name == me:
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
        """Names found among processes: comm equals the name (kernel truncates comm to 15 chars) or the
        basename of the executable (first cmdline token) equals it. Arguments are ignored, so a
        `gopt tune cs2` command line never counts as the game running."""
        found = []
        for name in names:
            nl = name.lower()
            for comm, cmd in processes:
                exe = cmd.split(" ", 1)[0] if cmd else ""
                base = exe.replace("\\", "/").rsplit("/", 1)[-1].lower()
                if comm.lower() == nl[:15] or base == nl:
                    found.append(name)
                    break
        return found

    @staticmethod
    def steam_running(processes: list[tuple[str, str]]) -> bool:
        for comm, cmd in processes:
            if comm in ("steam", "steamwebhelper") or re.search(r"/ubuntu12_32/steam(\s|$)", cmd):
                return True
        return False


def proton_major(name: str | None) -> int | None:
    """Major Proton version from a tool name or version file: proton_9 -> 9, GE-Proton10-25 -> 10,
    proton-10.0-3 -> 10; Experimental counts as current (99). None when unknown."""
    if not name:
        return None
    if "experimental" in name.lower() or "hotfix" in name.lower():
        return 99
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def dlss_note(tool: str | None) -> str:
    """What Proton needs for DLSS on the NVIDIA proprietary driver (ADAPTERS-RESEARCH.md 1.7)."""
    major = proton_major(tool)
    if major is None:
        return ("DLSS: Proton 9 or newer enables DXVK-NVAPI by default and copies nvngx.dll into the prefix; "
                "the Proton version in use is unknown, check Steam > Properties > Compatibility")
    if major < 9:
        return f"DLSS: {tool} is older than Proton 9; add PROTON_ENABLE_NVAPI=1 to the launch options or pick Proton 9+"
    return f"DLSS: {tool} enables DXVK-NVAPI by default; nothing to add to the launch options"


def strip_forbidden(options: str, forbid: list[str]) -> tuple[str, list[str]]:
    """Remove whitespace separated tokens that start with a forbidden string. Returns (options, removed)."""
    kept, removed = [], []
    for tok in options.split():
        if tok != "%command%" and any(tok.startswith(f) or tok.split("=", 1)[0] == f for f in forbid):
            removed.append(tok)
        else:
            kept.append(tok)
    return " ".join(kept), removed


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
