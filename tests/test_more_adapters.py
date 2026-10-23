"""The nineteen adapters added late on 23 Oct 2026 (branch more-adapters) against the fake Steam root:
every one loads and is listed, guessed keys are never written, file-unknown and unsupported-format adapters
measure only, the glob path and info keys work, and a discovered Witcher 3 key is written losslessly."""

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from gopt.adapters import Adapter, DATA_DIR
from gopt.cli import main
from gopt.paths import Paths
from gopt.safety import sha256_of

FIX = Path(__file__).parent / "fixtures"
LOG = str(FIX / "mangohud_cs2_pass.csv")

# id: (appid, name, install folder, runtime) as in Matthew's `gopt library`, 23 Oct 2026
NEW = {
    "legolotr": (214510, "LEGO® The Lord of the Rings™", "LEGO The Lord of the Rings", "proton"),
    "deeprockgalactic": (548430, "Deep Rock Galactic", "Deep Rock Galactic", "proton"),
    "detroit": (1222140, "Detroit: Become Human", "Detroit Become Human", "proton"),
    "discoelysium": (632470, "Disco Elysium", "Disco Elysium", "proton"),
    "dishonored": (205100, "Dishonored", "Dishonored", "proton"),
    "hades": (1145360, "Hades", "Hades", "proton"),
    "hotlinemiami": (219150, "Hotline Miami", "Hotline Miami", "native"),
    "lethalcompany": (1966720, "Lethal Company", "Lethal Company", "proton"),
    "megabonk": (3405340, "Megabonk", "Megabonk", "native"),
    "mhstories2": (1277400, "Monster Hunter Stories 2: Wings of Ruin", "MHST2", "proton"),
    "riskofrain2": (632360, "Risk of Rain 2", "Risk of Rain 2", "proton"),
    "slimerancher": (433340, "Slime Rancher", "Slime Rancher", "native"),
    "breachwizards": (1043810, "Tactical Breach Wizards", "Tactical Breach Wizards", "proton"),
    "terraria": (105600, "Terraria", "Terraria", "native"),
    "witcher3": (292030, "The Witcher 3: Wild Hunt", "The Witcher 3", "proton"),
    "darktide": (1361210, "Warhammer 40,000: Darktide", "Warhammer 40,000 DARKTIDE", "proton"),
    "mechanicus": (673880, "Warhammer 40,000: Mechanicus", "Warhammer 40000 Mechanicus", "native"),
    "vermintide2": (552500, "Warhammer: Vermintide 2", "Warhammer Vermintide 2", "proton"),
    "xcom2": (268500, "XCOM 2", "XCOM 2", "proton"),
}
CONFIDENCE = {"needs discover: keys", "needs discover: file", "measure only: format", "measure only: file known"}
KEYS_GUESSED = ("deeprockgalactic", "witcher3", "xcom2")


def add_games(steam):
    root = steam["root"]
    pfx = lambda a: root / "steamapps" / "compatdata" / str(a) / "pfx"
    for gid, (appid, name, folder, runtime) in NEW.items():
        (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{folder}"\n'
            f'\t"SizeOnDisk"\t\t"1000"\n}}\n')
        inst = root / "steamapps" / "common" / folder
        inst.mkdir(parents=True)
        if runtime == "native":
            exe = inst / "game.x86_64"
            exe.write_bytes(b"\x7fELF")
            exe.chmod(0o755)
        else:
            (inst / "game.exe").write_bytes(b"MZ")
            pfx(appid).mkdir(parents=True)
    docs = lambda a: pfx(a) / "drive_c/users/steamuser/Documents"
    files = {}
    w3 = docs(292030) / "The Witcher 3"
    w3.mkdir(parents=True)
    files["witcher3"] = shutil.copy(FIX / "witcher3_dx12user.settings", w3 / "dx12user.settings")
    drg = root / "steamapps/common/Deep Rock Galactic/FSD/Saved/Config/WindowsNoEditor"
    drg.mkdir(parents=True)
    files["deeprockgalactic"] = shutil.copy(FIX / "drg_GameUserSettings.ini", drg / "GameUserSettings.ini")
    xc = docs(268500) / "My Games/XCOM2/XComGame/Config"
    xc.mkdir(parents=True)
    files["xcom2"] = shutil.copy(FIX / "xcom2_XComEngine.ini", xc / "XComEngine.ini")
    di = docs(205100) / "My Games/Dishonored/DishonoredGame/Config"
    di.mkdir(parents=True)
    files["dishonored"] = shutil.copy(FIX / "dishonored_DishonoredEngine.ini", di / "DishonoredEngine.ini")
    de = pfx(632470) / "drive_c/users/steamuser/AppData/LocalLow/ZAUM Studio/Disco Elysium/Settings"
    de.mkdir(parents=True)
    files["discoelysium"] = shutil.copy(FIX / "discoelysium_Settings.json", de / "Settings.json")
    return {k: Path(v) for k, v in files.items()}


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
    return {"steam": steam, "paths": Paths(steam["home"]), "data": data, "files": files}


def run(argv, env):
    lines = []
    code = main(argv, out=lambda s="": lines.append(str(s)), paths=env["paths"])
    return code, "\n".join(lines)


def tune(game, env, n=2):
    argv = ["tune", game, "--goal", "3840x2160@60", "--apply"]
    for _ in range(n):
        argv += ["--log-file", LOG]
    return run(argv, env)


def all_shas(env):
    return {g: sha256_of(p) for g, p in env["files"].items()}


@pytest.mark.parametrize("gid", sorted(NEW))
def test_adapter_file_is_complete(gid):
    with open(DATA_DIR / f"{gid}.toml", "rb") as f:
        d = tomllib.load(f)
    ad = Adapter.load(gid, DATA_DIR)
    appid, _, _, runtime = NEW[gid]
    assert ad.id == gid and ad.appid == appid and ad.runtime == runtime
    assert d["game"]["confidence"] in CONFIDENCE
    assert ad.processes and ad.program and ad.benchmark.get("instructions")
    assert ad.launch_prefix == "mangohud" and "LD_PRELOAD" in ad.launch_forbid
    assert "ADAPTERS-RESEARCH.md 9." in Path(ad.source).read_text()[:400]   # header points at the research section
    if d["game"]["confidence"] == "needs discover: keys":
        assert ad.settings and all(s.guess and not s.usable for s in ad.settings)
    else:
        assert not ad.settings                                          # nothing to tune without confirmed keys
    if d["game"]["confidence"] in ("needs discover: file", "measure only: format"):
        assert not ad.has_settings_file and ad.settings_note
    for s in ad.settings:
        assert len(s.levels) == len(s.labels) == len(s.cost) and s.cost == sorted(s.cost)


def test_appids_are_unique_across_all_adapters():
    ids = {}
    for gid in Adapter.available(DATA_DIR):
        a = Adapter.load(gid, DATA_DIR)
        assert a.appid not in ids, (gid, ids.get(a.appid))
        ids[a.appid] = gid


def test_library_and_games_list_every_new_adapter_with_matching_runtime(env):
    code, text = run(["library"], env)
    assert code == 0
    for gid in NEW:
        assert gid in text, gid
    code, text = run(["games"], env)
    assert code == 0 and "WARNING" not in text, text
    for gid, (_, name, _, _) in NEW.items():
        assert Adapter.load(gid).name in text


@pytest.mark.parametrize("gid", KEYS_GUESSED)
def test_guessed_keys_are_never_written(env, gid):
    before = all_shas(env)
    code, text = run(["plan", gid, "--goal", "3840x2160@60"], env)
    assert code == 0 and f"left out until `gopt discover {gid}`" in text, text
    code, text = tune(gid, env)
    assert code == 0 and "measure only" in text, text
    assert all_shas(env) == before
    code, text = run(["show", gid], env)
    assert code == 0 and "guessed key" in text


def test_show_reads_current_values_of_guessed_keys(env):
    code, text = run(["show", "witcher3"], env)
    assert "HairWorksLevel" in text and "All" in text and "FoliageDistanceScale" in text
    code, text = run(["show", "deeprockgalactic"], env)
    assert "sg.ShadowQuality" in text and "Ultra" in text
    code, text = run(["show", "xcom2"], env)
    assert "AmbientOcclusion" in text and "True" in text


def test_witcher3_vsync_and_cap_are_manual_steps(env):
    code, text = run(["plan", "witcher3", "--goal", "3840x2160@60"], env)
    assert "Maximum Frames Per Second: Unlimited" in text and "VSync: Off" in text


def test_witcher3_discovered_key_is_written_losslessly_and_undone(env):
    p = env["files"]["witcher3"]
    p.write_bytes(p.read_bytes().replace(b"HairWorksLevel=2", b"HairWorksLevel=0"))   # start at Off: a passing run climbs
    original = p.read_bytes()
    (env["data"] / "witcher3.learned.json").write_text(json.dumps({"keys": {"hairworks": {
        "key": "Rendering::HairWorksLevel", "levels": ["0", "1", "2"], "status": "V"}}}))
    code, text = tune("witcher3", env, n=3)
    assert code == 0, text
    now = p.read_bytes()
    assert now.count(b"\r\n") == original.count(b"\r\n")
    changed = [(a, b) for a, b in zip(original.split(b"\r\n"), now.split(b"\r\n")) if a != b]
    assert len(changed) == 1 and changed[0][0] == b"HairWorksLevel=0" and changed[0][1] != b"HairWorksLevel=0", changed
    run_id = sorted(x.name for x in env["paths"].runs.iterdir())[-1]
    code, text = run(["undo", run_id], env)
    assert code == 0 and p.read_bytes() == original


def test_witcher3_discover_records_a_slash_section_key(env, tmp_path):
    after = tmp_path / "after.settings"
    after.write_bytes((FIX / "witcher3_dx12user.settings").read_bytes().replace(
        b"FoliageDistanceScale=1\r\n", b"FoliageDistanceScale=0.6\r\n"))
    code, text = run(["discover", "witcher3", "--before", str(FIX / "witcher3_dx12user.settings"),
                      "--after", str(after), "--setting", "foliage", "--label", "Medium"], env)
    assert code == 0 and "Rendering/SpeedTree::FoliageDistanceScale" in text, text


def test_drg_settings_live_in_the_install_folder(env):
    from gopt.steam import Steam
    p = Adapter.load("deeprockgalactic").settings_path(Steam(env["steam"]["root"]))
    assert p == env["files"]["deeprockgalactic"] and "steamapps/common/Deep Rock Galactic/FSD" in str(p)


@pytest.mark.parametrize("gid", sorted(g for g in NEW if g not in KEYS_GUESSED and g not in ("discoelysium", "dishonored")))
def test_file_unknown_adapters_measure_only(env, gid):
    code, text = run(["show", gid], env)
    assert code == 0 and f"find-settings {gid}" in text, text
    code, text = tune(gid, env)
    assert code == 0 and "measure only" in text, text
    code, text = run(["discover", gid], env)
    assert code == 3 and "find-settings" in text


def test_disco_elysium_path_matches_either_company_case_and_is_never_written(env):
    before = sha256_of(env["files"]["discoelysium"])
    code, text = run(["show", "discoelysium"], env)
    assert code == 0 and "ZAUM Studio/Disco Elysium/Settings/Settings.json" in text, text
    code, text = tune("discoelysium", env)
    assert code == 0 and "measure only" in text
    assert sha256_of(env["files"]["discoelysium"]) == before
    company = env["files"]["discoelysium"].parents[2]
    company.rename(company.parent / "Zaum Studio")
    code, text = run(["show", "discoelysium"], env)
    assert code == 0 and "Zaum Studio/Disco Elysium" in text


def test_dishonored_shows_its_ini_values_and_never_writes(env):
    before = sha256_of(env["files"]["dishonored"])
    code, text = run(["show", "dishonored"], env)
    assert code == 0 and "anisotropic filtering" in text and "MaxAnisotropy" in text and " 4" in text
    assert "bForceNoStartupMovies" in text and "False" in text
    code, text = tune("dishonored", env)
    assert code == 0 and "measure only" in text
    assert sha256_of(env["files"]["dishonored"]) == before


def test_native_measure_only_adapters_write_nothing_under_home(env):
    """Only the tool's own folders and MangoHud's per app config may change under the home folder."""
    home = env["steam"]["home"]
    own = lambda p: "game-optimiser" in str(p) or "/.config/MangoHud/" in str(p)
    before = sorted(str(p) for p in home.rglob("*") if p.is_file() and not own(p))
    for gid in ("terraria", "hotlinemiami", "megabonk", "slimerancher", "mechanicus"):
        code, text = tune(gid, env)
        assert code == 0 and "measure only" in text, (gid, text)
    after = sorted(str(p) for p in home.rglob("*") if p.is_file() and not own(p))
    assert after == before
