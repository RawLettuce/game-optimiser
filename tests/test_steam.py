from pathlib import Path

import pytest

from gopt import Refusal
from gopt.steam import Steam, rewrite_launch_options


def test_libraries_and_apps(steam):
    s = Steam(steam["root"])
    libs = s.libraries()
    assert libs[0] == steam["root"]
    assert steam["lib2"] in libs
    apps = s.apps()
    names = [a.name for a in apps]
    assert names == ["Counter-Strike 2", "ELDEN RING", "Steamworks Common Redistributables", "Warframe"]
    wf = s.app(230410)
    assert wf.proton is True
    assert wf.size_bytes == 50000000000
    assert wf.install_path.endswith("steamapps/common/Warframe")
    cs2 = s.app(730)
    assert cs2.proton is False
    er = s.app(1245620)
    assert er.library == str(steam["lib2"])


def test_user_id_from_loginusers(steam):
    s = Steam(steam["root"])
    assert s.user_id() == 52079950
    assert s.userdata() == steam["userdata"]
    assert s.localconfig_path() == steam["localconfig"]


def test_compatdata_and_proton_version(steam):
    s = Steam(steam["root"])
    assert s.compatdata(230410).name == "230410"
    assert s.compatdata(730) is None
    assert s.proton_version(230410) == "proton-10.0-3"


def test_get_and_rewrite_launch_options(steam):
    s = Steam(steam["root"])
    assert s.get_launch_options(230410).startswith("gamescope")
    assert s.get_launch_options(730) is None
    old, new = s.launch_options_text(730, "mangohud %command%")
    assert old == steam["localconfig"].read_text()
    assert '"LaunchOptions"\t\t"mangohud %command%"' in new
    old2, new2 = s.launch_options_text(230410, "mangohud %command%")
    assert "gamescope" not in new2
    with pytest.raises(Refusal):
        s.launch_options_text(999999, "x")


def test_missing_root_refuses(tmp_path):
    with pytest.raises(Refusal):
        Steam(tmp_path / "nope")


def test_rewrite_launch_options_removes_gamescope_and_adds_mangohud():
    cur = "gamescope -W 3840 -H 2160 -r 240 -f -- %command%"
    assert rewrite_launch_options(cur, ["gamescope"], "mangohud") == "mangohud %command%"
    assert rewrite_launch_options(None, ["gamescope"], "mangohud") == "mangohud %command%"
    assert rewrite_launch_options("", ["gamescope"], None) == "%command%"
    assert rewrite_launch_options("PROTON_LOG=1 %command% -novid", ["gamescope"], "mangohud", ["--in-process-gpu"]) \
        == "PROTON_LOG=1 mangohud %command% -novid --in-process-gpu"
    # idempotent
    assert rewrite_launch_options("mangohud %command%", ["gamescope"], "mangohud") == "mangohud %command%"


def test_running_detection():
    procs = [("steam", "/var/home/m/.local/share/Steam/ubuntu12_32/steam -silent"),
             ("Warframe.x64.exe", "C:\\Warframe\\Warframe.x64.exe -cluster:public"),
             ("cs2", "/var/home/m/.local/share/Steam/steamapps/common/Counter-Strike Global Offensive/game/bin/linuxsteamrt64/cs2 -steam")]
    assert Steam.steam_running(procs)
    assert Steam.any_running(["Warframe.x64.exe", "Launcher.exe"], procs) == ["Warframe.x64.exe"]
    assert Steam.any_running(["cs2"], procs) == ["cs2"]
    assert Steam.any_running(["cs2"], [("cs2fake", "/opt/cs2fake")]) == []
    # the tool's own command line names the game but is not the game
    assert Steam.any_running(["cs2"], [("python3", "/usr/bin/python3 -m gopt tune cs2 --goal 240")]) == []
    assert Steam.any_running(["Warframe.x64.exe"], [("wine64-preloader", "Z:\\x\\Warframe.x64.exe -cluster:public")]) == ["Warframe.x64.exe"]
    assert not Steam.steam_running([("bash", "bash")])


def test_running_processes_reads_proc(tmp_path):
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "comm").write_text("cs2\n")
    (tmp_path / "123" / "cmdline").write_bytes(b"/x/linuxsteamrt64/cs2\0-steam\0")
    (tmp_path / "self").mkdir()
    procs = Steam.running_processes(tmp_path)
    assert procs == [("cs2", "/x/linuxsteamrt64/cs2 -steam")]


# ---- regressions from the first PC run, 23 Oct 2026 ----------------------------------------------

import os
import shutil as _sh

from conftest import build_steam_root


def test_symlinked_home_lists_each_library_once(tmp_path):
    # Bazzite: /home is a symlink to /var/home; Steam writes the real path into libraryfolders.vdf
    real = tmp_path / "var" / "home"
    real.mkdir(parents=True)
    (tmp_path / "home").symlink_to(real)
    paths = build_steam_root(real)
    lf = paths["root"] / "steamapps" / "libraryfolders.vdf"
    lf.write_text(lf.read_text())                    # already holds the real (resolved) paths
    via_link = tmp_path / "home" / "Steam"
    s = Steam(via_link)
    libs = s.libraries()
    assert len(libs) == 2                            # root + games2, not root twice
    assert len({os.path.realpath(p) for p in libs}) == 2
    ids = [a.appid for a in s.apps()]
    assert len(ids) == len(set(ids))
    # Also when /home vs /var/home is a bind mount (realpath does not collapse them, but st_ino matches):
    orig_realpath = os.path.realpath
    try:
        os.path.realpath = lambda p: str(p)
        assert len(Steam(via_link).libraries()) == 2
    finally:
        os.path.realpath = orig_realpath


def test_runtime_compat_mapping_beats_compatdata(steam):
    root = steam["root"]
    # CS2 is native but has a leftover compatdata folder; Warframe is mapped to Proton in config.vdf
    (root / "steamapps" / "compatdata" / "730").mkdir(parents=True)
    cs2 = root / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "bin" / "linuxsteamrt64" / "cs2"
    cs2.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 64)
    cs2.chmod(0o755)
    (root / "config" / "config.vdf").write_text(
        '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        '\t\t\t\t\t"0"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"proton_experimental"\n\t\t\t\t\t}\n'
        '\t\t\t\t\t"230410"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name"\t\t"GE-Proton10-25"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t}\n'
        '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
    # ELDEN RING: Windows build only (an .exe), never launched (no compatdata, no mapping)
    er = steam["lib2"] / "steamapps" / "common" / "ELDEN RING" / "Game"
    er.mkdir(parents=True)
    (er / "eldenring.exe").write_bytes(b"MZ" + b"\0" * 64)
    s = Steam(root)
    assert s.app(730).runtime == "native" and s.app(730).proton is False
    assert "ELF" in s.app(730).runtime_source
    wf = s.app(230410)
    assert wf.runtime == "proton" and wf.compat_tool == "GE-Proton10-25" and "CompatToolMapping" in wf.runtime_source
    assert s.app(1245620).runtime == "proton" and ".exe" in s.app(1245620).runtime_source


def test_runtime_ignores_linux_eac_library_in_a_windows_game(steam):
    d = steam["lib2"] / "steamapps" / "common" / "ELDEN RING"
    (d / "EasyAntiCheat").mkdir(parents=True)
    so = d / "EasyAntiCheat" / "easyanticheat_x64.so"
    so.write_bytes(b"\x7fELF" + b"\0" * 60)
    so.chmod(0o755)
    (d / "game.exe").write_bytes(b"MZ")
    assert Steam(steam["root"]).app(1245620).runtime == "proton"


def test_runtime_unknown_falls_back_to_compatdata_with_a_question_mark(steam):
    # Warframe's install folder is empty in the fixture and there is no mapping: only compatdata says Proton
    a = Steam(steam["root"]).app(230410)
    assert a.runtime == "proton?" and "compatdata" in a.runtime_source


def test_library_cli_prints_detected_runtime(steam, tmp_path, monkeypatch):
    from gopt import cli
    from gopt.paths import Paths
    cs2 = steam["root"] / "steamapps" / "common" / "Counter-Strike Global Offensive" / "game" / "bin" / "linuxsteamrt64" / "cs2"
    cs2.write_bytes(b"\x7fELF" + b"\0" * 60)
    cs2.chmod(0o755)
    (steam["root"] / "steamapps" / "compatdata" / "730").mkdir()
    monkeypatch.setenv("GOPT_STEAM_ROOT", str(steam["root"]))
    lines = []
    cli.main(["library"], out=lines.append, paths=Paths(tmp_path / "h"))
    row = [l for l in lines if "Counter-Strike 2" in l][0]
    assert " native " in row



def test_forbidden_tokens_are_stripped_and_dlss_note():
    from gopt.steam import strip_forbidden, proton_major, dlss_note
    out, removed = strip_forbidden("PROTON_USE_WINED3D=1 mangohud %command% -high", ["PROTON_USE_WINED3D", "-high"])
    assert out == "mangohud %command%" and removed == ["PROTON_USE_WINED3D=1", "-high"]
    assert proton_major("GE-Proton10-25") == 10 and proton_major("proton_9") == 9
    assert proton_major("proton-8.0-5") == 8 and proton_major("proton_experimental") == 99 and proton_major(None) is None
    assert "PROTON_ENABLE_NVAPI=1" in dlss_note("proton_8")
    assert "nothing to add" in dlss_note("GE-Proton10-25") and "unknown" in dlss_note(None)


def test_warframe_target_drops_gamescope_and_grab_cursor(steam):
    from gopt.adapters import Adapter
    from gopt.session import Session
    from gopt.paths import Paths
    sess = Session(Adapter.load("warframe"), Steam(steam["root"]), Paths(steam["home"]))
    assert sess.launch_option_target() == "mangohud %command%"
    assert any("Borderless" in a for a in sess.ad.launch_advice)
    assert any("steam_app_230410" in a and "DP-2" in a for a in sess.ad.launch_advice)



def test_apps_are_read_once_per_steam_object(steam, monkeypatch):
    s = Steam(steam["root"])
    calls = []
    real = Steam.scan_binaries
    monkeypatch.setattr(Steam, "scan_binaries", staticmethod(lambda *a, **k: calls.append(1) or real(*a, **k)))
    s.app(730), s.app(230410), s.apps()
    first = len(calls)
    s.app(730)
    assert len(calls) == first and first <= len(s.apps())
