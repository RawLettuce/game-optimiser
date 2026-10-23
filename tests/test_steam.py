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
    assert not Steam.steam_running([("bash", "bash")])


def test_running_processes_reads_proc(tmp_path):
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "comm").write_text("cs2\n")
    (tmp_path / "123" / "cmdline").write_bytes(b"/x/linuxsteamrt64/cs2\0-steam\0")
    (tmp_path / "self").mkdir()
    procs = Steam.running_processes(tmp_path)
    assert procs == [("cs2", "/x/linuxsteamrt64/cs2 -steam")]
