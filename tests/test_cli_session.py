"""End to end tests of the CLI and the session loop against the fake Steam root and fixture logs."""

import json
import shutil
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.adapters import DATA_DIR
from gopt.cli import main
from gopt.paths import Paths
from gopt.safety import sha256_of
from gopt.session import parse_goal

FIX = Path(__file__).parent / "fixtures"


class Out:
    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        self.lines.append(str(s))

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def env(steam, tmp_path, monkeypatch):
    """GOPT_HOME and GOPT_STEAM_ROOT point at the fake layout; no processes running; isolated adapter data."""
    monkeypatch.setenv("GOPT_HOME", str(steam["home"]))
    monkeypatch.setenv("GOPT_STEAM_ROOT", str(steam["root"]))
    # isolate learned files from the real data dir
    data = tmp_path / "adapters"
    data.mkdir()
    for f in DATA_DIR.glob("*.toml"):
        shutil.copy(f, data / f.name)
    monkeypatch.setenv("GOPT_ADAPTER_DIR", str(data))
    import gopt.steam as steam_mod
    monkeypatch.setattr(steam_mod.Steam, "running_processes", staticmethod(lambda proc=None: []))
    import gopt.hwprobe as hw
    monkeypatch.setattr(hw, "probe", lambda: {
        "gopt_version": "t", "probed_at": "t", "cpu": {"model": "Ryzen 5 3600"}, "memory": {"total_mb": 16000},
        "gpu": {"vendor": "nvidia", "name": "RTX 3070", "vram_mb": 8192, "driver": "580"},
        "display": {"outputs": [{"name": "DP-2", "active_mode": "3840x2160@240", "refresh_hz": 240, "scale": 1.5, "hdr": False}]},
        "tools": {"mangohud": True}})
    paths = Paths(steam["home"])
    return {"steam": steam, "paths": paths, "data": data}


def run(argv, env):
    out = Out()
    code = main(argv, out=out, paths=env["paths"])
    return code, out.text


def test_parse_goal():
    assert parse_goal("3840x2160@90", None, None)[0] == 90.0
    assert parse_goal("90", None, None)[2] is None
    fps, low, _, why = parse_goal(None, "balanced", 240)
    assert fps == 180.0 and low == 0.7
    with pytest.raises(Refusal):
        parse_goal("fast", None, None)
    with pytest.raises(Refusal):
        parse_goal(None, "quality", None)


def test_library_lists_games_and_adapters(env):
    code, text = run(["library"], env)
    assert code == 0
    assert "Warframe" in text and "warframe" in text and "ELDEN RING" in text and "games2" in text
    assert "proton" in text and "native" in text
    code, text = run(["library", "--games-only"], env)
    assert "Redistributables" not in text
    code, text = run(["library", "--json"], env)
    data = json.loads(text)
    assert {a["appid"] for a in data} == {230410, 730, 228980, 1245620}


def test_games_and_show(env):
    code, text = run(["games"], env)
    assert code == 0 and "proton-10.0-3" in text and "(found)" in text and "gamescope" in text
    code, text = run(["show", "warframe"], env)
    assert code == 0 and "SQ_HIGH" in text and "absent (default)" in text
    code, text = run(["show", "cs2"], env)
    assert code == 0 and "Very High" in text


def test_probe_writes_cache(env):
    code, text = run(["probe"], env)
    assert code == 0 and "cache refreshed" in text and env["paths"].hardware_cache.exists()
    code, text = run(["probe"], env)
    assert "cache unchanged" in text


def test_plan_is_read_only(env):
    s = env["steam"]
    before = {p: sha256_of(p) for p in (s["eecfg"], s["cs2_video"], s["localconfig"])}
    code, text = run(["plan", "warframe", "--goal", "3840x2160@90"], env)
    assert code == 0
    assert "Plan for Warframe" in text and "mangohud %command%" in text and "MANUAL" in text
    assert {p: sha256_of(p) for p in before} == before
    code, text = run(["plan", "cs2", "--priority", "fps"], env)
    assert "240 fps" in text
    code, text = run(["plan", "cs2"], env)
    assert code == 3


def test_tune_dry_run_writes_nothing(env):
    s = env["steam"]
    before = {p: sha256_of(p) for p in (s["eecfg"], s["cs2_video"], s["localconfig"])}
    code, text = run(["tune", "cs2", "--goal", "240"], env)
    assert code == 0 and "Dry run" in text
    assert {p: sha256_of(p) for p in before} == before
    assert not list(env["paths"].mangohud_dir.glob("*.conf"))
    assert not env["paths"].runs.exists()


def test_tune_cs2_with_fixture_logs_reaches_goal_and_undo_restores(env):
    s = env["steam"]
    original = s["cs2_video"].read_bytes()
    logs = [str(FIX / "mangohud_cs2_pass.csv")] * 6
    argv = ["tune", "cs2", "--goal", "240", "--apply"]
    for l in logs:
        argv += ["--log-file", l]
    code, text = run(argv, env)
    assert code == 0, text
    assert "GOAL MET" in text or "comfortable margin" in text
    assert s["cs2_video"].read_bytes() != original
    run_dirs = list(env["paths"].runs.iterdir())
    assert len(run_dirs) == 1
    rd = run_dirs[0]
    report = (rd / "game-optimiser-report.txt").read_text()
    assert report.startswith("game-optimiser 0.1.0 report")
    assert "undo: python3 -m gopt undo" in report
    manifest = json.loads((rd / "MANIFEST.json").read_text())
    originals = {e["original"] for e in manifest["entries"]}
    assert str(s["cs2_video"]) in originals
    assert str(env["paths"].mangohud_dir / "cs2.conf") in originals
    # MangoHud config restored at the end (placeholder comment), launch options never written
    assert (env["paths"].mangohud_dir / "cs2.conf").read_text().startswith("# created by game-optimiser")
    assert s["localconfig"].read_text() == (FIX / "localconfig.vdf").read_text()
    learned = json.loads((env["data"] / "cs2.learned.json").read_text())
    assert learned["model"]["bound"] in ("met", "gpu", "cpu", "unknown")
    # undo
    code, text = run(["undo", rd.name], env)
    assert code == 0 and s["cs2_video"].read_bytes() == original
    code, text = run(["undo", rd.name], env)
    assert code == 3


def test_tune_warframe_goal_not_met_exit_2_and_lowest_rung_left(env):
    s = env["steam"]
    logs = [str(FIX / "mangohud_warframe_gpu_bound.csv")] * 6     # ~77 fps against a goal of 90 x 1.25
    argv = ["tune", "warframe", "--goal", "3840x2160@90", "--apply"]
    for l in logs:
        argv += ["--log-file", l]
    code, text = run(argv, env)
    assert code == 2, text
    assert "Goal not met" in text
    cfg = s["eecfg"].read_text()
    assert "Graphics.AutoDetectGraphicsSettings=0" in cfg
    assert "Graphics.ShadowQuality=SQ_LOW" in cfg
    # native first, then DLSS Quality only (never Balanced or Performance), fastest measured rung left applied
    assert "Graphics.Upscaling=DLSS_QUALITY" in cfg
    i_native, i_dlss = text.index("native rung"), text.index("trying DLSS Quality")
    assert i_native < i_dlss and "Upscaling=Off (native)" in text[:i_dlss]
    assert "DLSS Performance" not in text.split("search order")[1] and "DLSS Balanced" not in text
    # key bindings untouched
    assert "MOVE_FORWARD=W" in cfg


def test_tune_refuses_when_game_running(env, monkeypatch):
    import gopt.steam as steam_mod
    monkeypatch.setattr(steam_mod.Steam, "running_processes",
                        staticmethod(lambda proc=None: [("cs2", "/x/linuxsteamrt64/cs2 -steam")]))
    s = env["steam"]
    before = sha256_of(s["cs2_video"])
    code, text = run(["tune", "cs2", "--goal", "240", "--apply", "--log-file", str(FIX / "mangohud_cs2_pass.csv")], env)
    assert code == 3 and "running" in text
    assert sha256_of(s["cs2_video"]) == before


def test_write_launch_options_requires_steam_closed_and_yes(env, monkeypatch):
    s = env["steam"]
    import gopt.steam as steam_mod
    monkeypatch.setattr(steam_mod.Steam, "running_processes",
                        staticmethod(lambda proc=None: [("steam", "/x/ubuntu12_32/steam")]))
    code, text = run(["tune", "cs2", "--goal", "240", "--apply", "--write-launch-options", "--yes",
                      "--log-file", str(FIX / "mangohud_cs2_pass.csv")], env)
    assert code == 3 and "Steam is running" in text
    monkeypatch.setattr(steam_mod.Steam, "running_processes", staticmethod(lambda proc=None: []))
    code, text = run(["tune", "cs2", "--goal", "240", "--apply", "--write-launch-options", "--yes"]
                     + sum([["--log-file", str(FIX / "mangohud_cs2_pass.csv")] for _ in range(6)], []), env)
    assert code == 0, text
    lc = s["localconfig"].read_text()
    assert '"LaunchOptions"\t\t"mangohud %command% -condebug"' in lc
    assert "gamescope -W 3840" in lc      # Warframe's options untouched


def test_stale_plan_is_refused(env, tmp_path):
    s = env["steam"]
    code, text = run(["plan", "cs2", "--goal", "240", "--save", str(tmp_path / "p.json")], env)
    assert code == 0
    s["cs2_video"].write_text(s["cs2_video"].read_text() + "\n")
    code, text = run(["apply", str(tmp_path / "p.json"), "--apply", "--log-file", str(FIX / "mangohud_cs2_pass.csv")], env)
    assert code == 3 and "stale plan" in text


def test_measure_from_log(env):
    code, text = run(["measure", "warframe", "--log-file", str(FIX / "mangohud_warframe_spiky.csv")], env)
    assert code == 0
    m = json.loads(text)
    assert m["spikes_per_min"] > 3


def test_discover_non_interactive_records_key_and_completes_levels(env, tmp_path):
    before = tmp_path / "before.cfg"
    shutil.copy(FIX / "EE.cfg", before)
    labels = ["Disabled", "Low", "Medium", "High", "Ludicrous"]
    values = ["GPQ_OFF", "GPQ_LOW", "GPQ_MED", "GPQ_HIGH", "GPQ_LUD"]
    prev = before
    for label, value in zip(labels, values):
        after = tmp_path / f"after_{label}.cfg"
        text = prev.read_text()
        if "Graphics.GPUParticlesQuality=" in text:
            import re
            text = re.sub(r"Graphics.GPUParticlesQuality=\S+", f"Graphics.GPUParticlesQuality={value}", text)
        else:
            text = text.replace("Graphics.ShadowQuality=SQ_HIGH", f"Graphics.ShadowQuality=SQ_HIGH\nGraphics.GPUParticlesQuality={value}")
        after.write_text(text)
        code, out = run(["discover", "warframe", "--before", str(prev), "--after", str(after),
                         "--setting", "gpu_particles", "--label", label], env)
        assert code == 0, out
        prev = after
    learned = json.loads((env["data"] / "warframe.learned.json").read_text())
    assert learned["keys"]["gpu_particles"]["key"] == "Graphics.GPUParticlesQuality"
    assert learned["keys"]["gpu_particles"]["levels"] == values
    assert learned["section"] == "Windows_Config,/EE/Types/Base/Config"
    # the adapter now uses the learned key
    code, out = run(["show", "warframe"], env)
    assert "Graphics.GPUParticlesQuality" in out and " V" in out


def test_discover_refuses_two_changed_keys(env, tmp_path):
    before = tmp_path / "b.cfg"
    after = tmp_path / "a.cfg"
    shutil.copy(FIX / "EE.cfg", before)
    after.write_text(before.read_text().replace("SQ_HIGH", "SQ_LOW").replace("TQ_LOW", "TQ_HIGH"))
    code, out = run(["discover", "warframe", "--before", str(before), "--after", str(after),
                     "--setting", "shadows", "--label", "Low"], env)
    assert code == 3 and "exactly one" in out


def test_selftest_and_report(env):
    code, text = run(["selftest"], env)
    assert code == 0 and "checks passed" in text
    code, text = run(["report", "nope"], env)
    assert code == 3


def test_scene_is_offered_once_and_remembered(env):
    from gopt.adapters import Adapter
    from gopt.session import Session
    from gopt.steam import Steam
    asked = []
    ad = Adapter.load("warframe")
    sess = Session(ad, Steam(env["steam"]["root"]), env["paths"], out=lambda *a: None,
                   ask=lambda q: asked.append(q) or "2")
    pick = sess.choose_scene()
    assert pick["name"] == ad.benchmark["scene_options"][1]["name"] and len(asked) == 1
    assert sess.choose_scene()["name"] == pick["name"] and len(asked) == 1      # remembered, not asked again
    again = Adapter.load("warframe")
    assert again.learned["benchmark_scene"]["name"] == pick["name"]
    assert pick["name"] in Session(again, Steam(env["steam"]["root"]), env["paths"]).benchmark_instructions()
    # --scene overrides with a name that is not on the list
    assert sess.choose_scene("Cetus Scene")["name"] == "Cetus Scene"


def test_warframe_offers_two_or_three_scenes():
    from gopt.adapters import Adapter
    opts = Adapter.load("warframe").benchmark["scene_options"]
    assert 2 <= len(opts) <= 3 and all(o["name"] and o["why"] and o["setup"] for o in opts)
