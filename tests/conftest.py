"""Shared fixtures: a fake Steam root built from the fixture files."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def build_steam_root(tmp: Path, with_cs2_video: bool = True, with_eecfg: bool = True,
                     launch_options_for_cs2: str | None = None) -> dict:
    """Create a fake Steam layout under tmp. Returns the important paths."""
    root = tmp / "Steam"
    lib2 = tmp / "games2"
    (root / "config").mkdir(parents=True)
    (root / "steamapps").mkdir()
    (lib2 / "steamapps" / "common" / "ELDEN RING").mkdir(parents=True)
    # library folders
    text = (FIX / "libraryfolders.vdf").read_text()
    text = text.replace("__STEAM_ROOT__", str(root)).replace("__LIB2__", str(lib2))
    (root / "steamapps" / "libraryfolders.vdf").write_text(text)
    for name in ("appmanifest_230410.acf", "appmanifest_730.acf", "appmanifest_228980.acf"):
        shutil.copy(FIX / name, root / "steamapps" / name)
    shutil.copy(FIX / "appmanifest_1245620.acf", lib2 / "steamapps" / "appmanifest_1245620.acf")
    (root / "steamapps" / "common" / "Warframe").mkdir(parents=True)
    cs2dir = root / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "bin" / "linuxsteamrt64"
    cs2dir.mkdir(parents=True)
    (cs2dir / "cs2").write_bytes(b"\x7fELF")
    (cs2dir / "cs2").chmod(0o755)                  # Steam installs Linux executables with the x bit
    # users
    shutil.copy(FIX / "loginusers.vdf", root / "config" / "loginusers.vdf")
    userdata = root / "userdata" / "52079950"      # 76561198012345678 - 76561197960265728
    (userdata / "config").mkdir(parents=True)
    lc = (FIX / "localconfig.vdf").read_text()
    if launch_options_for_cs2 is not None:
        lc = lc.replace('"LastPlayed"\t\t"1761100000"',
                        f'"LastPlayed"\t\t"1761100000"\n\t\t\t\t\t\t"LaunchOptions"\t\t"{launch_options_for_cs2}"')
    (userdata / "config" / "localconfig.vdf").write_text(lc)
    cs2cfg = userdata / "730" / "local" / "cfg"
    cs2cfg.mkdir(parents=True)
    if with_cs2_video:
        shutil.copy(FIX / "cs2_video.txt", cs2cfg / "cs2_video.txt")
        shutil.copy(FIX / "cs2_video.txt", cs2cfg / "cs2_video.bak")
    # proton prefix for warframe
    wfdir = root / "steamapps" / "compatdata" / "230410" / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Warframe"
    wfdir.mkdir(parents=True)
    if with_eecfg:
        shutil.copy(FIX / "EE.cfg", wfdir / "EE.cfg")
    (root / "steamapps" / "compatdata" / "230410" / "version").write_text("proton-10.0-3\n")
    home = tmp / "home"
    (home / ".config" / "MangoHud").mkdir(parents=True)
    return {"root": root, "lib2": lib2, "userdata": userdata, "eecfg": wfdir / "EE.cfg",
            "cs2_video": cs2cfg / "cs2_video.txt", "localconfig": userdata / "config" / "localconfig.vdf",
            "home": home, "mangohud_dir": home / ".config" / "MangoHud"}


@pytest.fixture
def steam(tmp_path):
    return build_steam_root(tmp_path)


@pytest.fixture
def fixtures_dir():
    return FIX
