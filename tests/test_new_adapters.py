"""The five adapters added on 23 Oct 2026 against the fake Steam root: paths, measure only behaviour,
guessed keys, the created autoexec, the whole file check on Brotato's save and find-settings."""

import json
import shutil
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.adapters import Adapter, DATA_DIR
from gopt.cli import main
from gopt.paths import Paths
from gopt.safety import sha256_of

FIX = Path(__file__).parent / "fixtures"
LOG = str(FIX / "mangohud_cs2_pass.csv")

GAMES = {4000: ("Garry's Mod", "GarrysMod"), 397540: ("Borderlands 3", "Borderlands 3"),
         1942280: ("Brotato", "Brotato"), 960090: ("Bloons TD 6", "BloonsTD6"),
         1337520: ("Risk of Rain Returns", "Risk of Rain Returns")}


def add_games(steam):
    root = steam["root"]
    for appid, (name, folder) in GAMES.items():
        (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{folder}"\n'
            f'\t"LastPlayed"\t\t"1761000000"\n\t"SizeOnDisk"\t\t"1000"\n}}\n')
        inst = root / "steamapps" / "common" / folder
        inst.mkdir(parents=True)
        (inst / "game.exe").write_bytes(b"MZ")
        (root / "steamapps" / "compatdata" / str(appid) / "pfx").mkdir(parents=True)
    pfx = lambda a: root / "steamapps" / "compatdata" / str(a) / "pfx"
    (root / "steamapps" / "common" / "GarrysMod" / "garrysmod" / "cfg").mkdir(parents=True)
    ue = pfx(397540) / "drive_c/users/steamuser/Documents/My Games/Borderlands 3/Saved/Config/WindowsNoEditor"
    ue.mkdir(parents=True)
    shutil.copy(FIX / "GameUserSettings.ini", ue / "GameUserSettings.ini")
    br = pfx(1942280) / "drive_c/users/steamuser/AppData/Roaming/Brotato/76561198012345678"
    br.mkdir(parents=True)
    shutil.copy(FIX / "brotato_save_v2.json", br / "save_v2.json")
    shutil.copy(FIX / "user.reg", pfx(960090) / "user.reg")
    return {"autoexec": root / "steamapps/common/GarrysMod/garrysmod/cfg/autoexec.cfg",
            "ue_ini": ue / "GameUserSettings.ini", "brotato": br / "save_v2.json", "user_reg": pfx(960090) / "user.reg",
            "rorr_user": pfx(1337520) / "drive_c/users/steamuser/AppData/Roaming/Risk_of_Rain_Returns/user_1"}


@pytest.fixture
def env(steam, tmp_path, monkeypatch):
    monkeypatch.setenv("GOPT_HOME", str(steam["home"]))
    monkeypatch.setenv("GOPT_STEAM_ROOT", str(steam["root"]))
    data = tmp_path / "adapters"
    data.mkdir()
    for f in DATA_DIR.glob("*.toml"):
        shutil.copy(f, data / f.name)
    monkeypatch.setenv("GOPT_ADAPTER_DIR", str(data))
    import gopt.steam as steam_mod
    import gopt.hwprobe as hw
    monkeypatch.setattr(steam_mod.Steam, "running_processes", staticmethod(lambda proc=None: []))
    monkeypatch.setattr(hw, "probe", lambda: {"gpu": {"vram_mb": 8192}, "display": {"outputs": [
        {"name": "DP-2", "active_mode": "3840x2160@240", "refresh_hz": 240.0}]}})
    files = add_games(steam)
    return {"steam": steam, "paths": Paths(steam["home"]), "data": data, **files}


def run(argv, env):
    lines = []
    code = main(argv, out=lambda s="": lines.append(str(s)), paths=env["paths"])
    return code, "\n".join(lines)


def tune(game, env, n=3, extra=()):
    argv = ["tune", game, "--goal", "3840x2160@60", "--apply", *extra]
    for _ in range(n):
        argv += ["--log-file", LOG]
    return run(argv, env)


def test_library_shows_the_new_adapters(env):
    code, text = run(["library"], env)
    for gid in ("garrysmod", "borderlands3", "brotato", "bloonstd6", "riskofrainreturns"):
        assert gid in text


def test_garrysmod_creates_autoexec_writes_cvars_and_undo_restores(env):
    assert not env["autoexec"].exists()
    code, text = run(["plan", "garrysmod", "--goal", "3840x2160@60"], env)
    assert code == 0 and "does not exist yet" in text and not env["autoexec"].exists()
    code, text = tune("garrysmod", env)
    assert code in (0, 2), text
    cfg = env["autoexec"].read_text()
    assert cfg.startswith("// created by game-optimiser") and 'fps_max "0"' in cfg and "mat_antialias" in cfg
    run_id = sorted(p.name for p in env["paths"].runs.iterdir())[-1]
    code, text = run(["undo", run_id], env)
    assert code == 0 and env["autoexec"].read_text() == "// created by game-optimiser; safe to delete\n"


def test_borderlands3_guessed_keys_are_never_written(env):
    before = sha256_of(env["ue_ini"])
    code, text = run(["plan", "borderlands3", "--goal", "3840x2160@60"], env)
    assert "left out until `gopt discover borderlands3`" in text and "volumetric_fog" in text
    code, text = tune("borderlands3", env, n=2)
    assert code == 0, text
    assert sha256_of(env["ue_ini"]) == before
    code, text = run(["show", "borderlands3"], env)
    assert "sg.ShadowQuality" in text and "guessed key" in text


def test_borderlands3_discovered_key_enters_the_ladder(env):
    (env["data"] / "borderlands3.learned.json").write_text(json.dumps({"keys": {"shadows": {
        "key": "ScalabilityGroups::sg.ShadowQuality", "levels": ["0", "1", "2", "3", "4"], "status": "V"}}}))
    code, text = tune("borderlands3", env, n=3)
    assert code == 0, text
    ini = env["ue_ini"].read_bytes().decode("utf-8")
    assert "\r\nsg.ShadowQuality=" in ini and ini.count("\r\n") == (FIX / "GameUserSettings.ini").read_bytes().count(b"\r\n")


def test_borderlands3_discover_records_section_qualified_keys(env, tmp_path):
    after = tmp_path / "after.ini"
    after.write_bytes((FIX / "GameUserSettings.ini").read_bytes().replace(b"VolumetricFogQuality=3", b"VolumetricFogQuality=1"))
    code, text = run(["discover", "borderlands3", "--before", str(FIX / "GameUserSettings.ini"), "--after", str(after),
                      "--setting", "volumetric_fog", "--label", "Low"], env)
    assert code == 0 and "/Script/OakGame.OakGameUserSettings::VolumetricFogQuality" in text


def test_brotato_write_touches_only_the_planned_key(env):
    from gopt.session import Session
    from gopt.safety import RunDir
    from gopt.steam import Steam
    ad = Adapter.load("brotato")
    sess = Session(ad, Steam(env["steam"]["root"]), env["paths"], out=lambda *a: None)
    sess.run = RunDir(env["paths"].runs, "t-brotato").create()
    original = json.loads(env["brotato"].read_text())
    sess._apply_changes({"settings.optimize_end_waves": "true"}, "test")
    now = json.loads(env["brotato"].read_text())
    assert now["settings"]["optimize_end_waves"] is True and now["progress"] == original["progress"]
    with pytest.raises(Refusal):
        sess._apply_changes({"settings.no_such_key": "1"}, "test")     # never adds keys to the save


def test_brotato_and_bloons_measure_only_never_write_their_files(env):
    shas = {p: sha256_of(env[p]) for p in ("brotato", "user_reg")}
    for game in ("brotato", "bloonstd6"):
        code, text = tune(game, env, n=2)
        assert code == 0 and "measure only" in text, text
    assert {p: sha256_of(env[p]) for p in shas} == shas


def test_bloons_show_reads_unity_screen_prefs(env):
    code, text = run(["show", "bloonstd6"], env)
    assert code == 0 and "Unity screen width" in text and "3840" in text and "2160" in text


def test_brotato_two_save_folders_refuse(env):
    other = env["brotato"].parent.parent / "76561198000000000"
    other.mkdir()
    shutil.copy(env["brotato"], other / "save_v2.json")
    code, text = run(["show", "brotato"], env)
    assert code == 3 and "matched 2 files" in text


def test_risk_of_rain_returns_is_measure_only_until_found(env):
    code, text = run(["show", "riskofrainreturns"], env)
    assert code == 0 and "find-settings riskofrainreturns" in text
    code, text = tune("riskofrainreturns", env, n=2)
    assert code == 0 and "measure only" in text
    code, text = run(["discover", "riskofrainreturns"], env)
    assert code == 3 and "find-settings" in text


def test_find_settings_names_the_file_and_line(env, tmp_path):
    from gopt import findsettings as fs
    from gopt.steam import Steam
    env["rorr_user"].mkdir(parents=True)
    prefs = env["rorr_user"] / "prefs.json"
    prefs.write_text('{"vsync": 1, "fullscreen": 1}\n')
    roots = fs.roots_for(Steam(env["steam"]["root"]), 1337520)
    assert any(str(r).endswith("AppData/Roaming") for r in roots)
    before = fs.snapshot(roots)
    prefs.write_text('{"vsync": 0, "fullscreen": 1}\n')
    after = fs.snapshot(roots)
    fs.save(before, tmp_path / "b.json")
    fs.save(after, tmp_path / "a.json")
    code, text = run(["find-settings", "riskofrainreturns", "--before", str(tmp_path / "b.json"),
                      "--after", str(tmp_path / "a.json")], env)
    assert code == 0 and "changed: " in text and "prefs.json" in text
    assert '-{"vsync": 1, "fullscreen": 1}' in text and '+{"vsync": 0, "fullscreen": 1}' in text
    assert list((env["paths"].data_dir / "find-settings").glob("riskofrainreturns-*.txt"))
    code, text = run(["find-settings", "riskofrainreturns", "--before", str(tmp_path / "b.json"),
                      "--after", str(tmp_path / "b.json")], env)
    assert code == 4 and "no file changed" in text


def test_find_settings_skips_caches(env):
    from gopt import findsettings as fs
    d = env["rorr_user"].parent / "ShaderCache"
    d.mkdir(parents=True)
    (d / "x.bin").write_bytes(b"\0" * 10)
    snap = fs.snapshot([env["rorr_user"].parent])
    assert not any("ShaderCache" in p for p in snap)


def test_whole_file_check_refuses_a_change_outside_the_plan(env, monkeypatch):
    from gopt.session import Session
    from gopt.safety import RunDir
    from gopt.steam import Steam
    ad = Adapter.load("brotato")
    real = ad.apply_changes

    def sneaky(doc, changes):            # a buggy writer that also touches the save progress
        return real(doc, dict(changes, **{"progress.runs_won": "0"}))
    monkeypatch.setattr(ad, "apply_changes", sneaky)
    sess = Session(ad, Steam(env["steam"]["root"]), env["paths"], out=lambda *a: None)
    sess.run = RunDir(env["paths"].runs, "t-sneaky").create()
    with pytest.raises(Refusal, match="outside the plan"):
        sess._apply_changes({"settings.fullscreen": "false"}, "test")
