"""Regression tests from Matthew's read only PC checks, 23 Oct 2026 (~21:15): the real Warframe EE.cfg keys,
discover for keys the file does not have yet, the binary "230410" string in localconfig.vdf, `kscreen-doctor -j`,
and Proton Experimental 11 with no GE-Proton."""

import argparse
import json
import shutil
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.adapters import Adapter, DATA_DIR
from gopt.cli import cmd_discover, main
from gopt.parsers.keyvalues import KeyValues
from gopt.paths import Paths
from gopt.safety import RunDir, sha256_of, write_file
from gopt.steam import Steam, dlss_note

FIX = Path(__file__).parent / "fixtures"
PC_EECFG = FIX / "EE_pc_20261023.cfg"


class Out(list):
    def __call__(self, s=""):
        self.append(str(s))

    @property
    def text(self):
        return "\n".join(self)


@pytest.fixture
def env(steam, tmp_path, monkeypatch):
    """Fake Steam root with the PC's real EE.cfg key set, isolated adapter data, nothing running."""
    monkeypatch.setenv("GOPT_HOME", str(steam["home"]))
    monkeypatch.setenv("GOPT_STEAM_ROOT", str(steam["root"]))
    data = tmp_path / "adapters"
    data.mkdir()
    for f in DATA_DIR.glob("*.toml"):
        shutil.copy(f, data / f.name)
    monkeypatch.setenv("GOPT_ADAPTER_DIR", str(data))
    import gopt.steam as steam_mod
    monkeypatch.setattr(steam_mod.Steam, "running_processes", staticmethod(lambda proc=None: []))
    shutil.copy(PC_EECFG, steam["eecfg"])
    return {"steam": steam, "paths": Paths(steam["home"]), "data": data}


def run(argv, env):
    out = Out()
    return main(argv, out=out, paths=env["paths"]), out.text


# ---- 6. Warframe EE.cfg: the real keys -----------------------------------------------------------

def test_warframe_adapter_uses_upscalemethod_and_upscalequality():
    ad = Adapter.load("warframe")
    keys = [k for s in ad.settings for k in s.keys()] + [o.key for o in ad.overrides] + [i["key"] for i in ad.info_keys]
    assert "Graphics.Upscaling" not in keys
    ups = ad.setting("upscaling")
    assert ups.key == "Graphics.UpscaleMethod" and list(ups.extra_keys) == ["Graphics.UpscaleQuality"]
    assert ups.labels == ["DLSS Quality", "Off (native)"] and ups.fallback == "UM_DLSS"
    assert ups.values_for(0) == {"Graphics.UpscaleMethod": "UM_DLSS", "Graphics.UpscaleQuality": "UQ_QUALITY"}
    # the native value has no source: nothing is written until discover records it
    assert ups.guess and not ups.usable


def test_pc_eecfg_reads_as_dlss_quality_borderless(steam):
    shutil.copy(PC_EECFG, steam["eecfg"])
    ad = Adapter.load("warframe")
    vals = ad.read_settings(ad.settings_path(Steam(steam["root"])))
    assert ad.current_levels(vals)["upscaling"] == 0                     # DLSS Quality
    # UM_DLSS with another quality is not DLSS Quality
    assert ad.setting("upscaling").level_from(dict(vals, **{"Graphics.UpscaleQuality": "UQ_PERFORMANCE"})) is None
    doc = ad.load_doc(ad.settings_path(Steam(steam["root"])))
    assert doc.get("Graphics.WindowMode") == "MODE_BORDERLESS"
    assert (doc.get("Graphics.FullScreenSizeX"), doc.get("Graphics.FullScreenSizeY")) == ("3840", "2160")


def test_pc_eecfg_plan_is_measure_only_until_discover(env):
    code, text = run(["plan", "warframe", "--goal", "3840x2160@90"], env)
    assert code == 0, text
    waiting = text.split("left out until `gopt discover warframe`")[1].split("\n")[0]
    for sid in ("upscaling", "geometry", "shadows", "textures", "gpu_particles", "antialiasing", "bloom"):
        assert sid in waiting


def test_pc_eecfg_tune_writes_no_absent_key(env):
    before = env["steam"]["eecfg"].read_text()
    code, text = run(["tune", "warframe", "--goal", "3840x2160@90", "--apply", "--yes",
                      "--log-file", str(FIX / "mangohud_warframe_gpu_bound.csv")], env)
    after = env["steam"]["eecfg"].read_text()
    assert after == before, text                      # AutoDetectGraphicsSettings is already 0; nothing else is known


def test_show_prints_borderless_and_waiting_keys(env):
    code, text = run(["show", "warframe"], env)
    assert code == 0, text
    assert "MODE_BORDERLESS" in text and "UQ_QUALITY" in text
    assert "Graphics.ShadowQuality" in text and "not in the file: not tuned until discover" in text
    assert "guessed key or value: not tuned until discover" in text   # upscaling: native value unknown


def test_absent_key_rule_spares_adapters_that_create_their_file(steam):
    ad = Adapter.load("garrysmod")
    s = ad.settings[0]
    assert not ad.needs_discover(s, {}, Path("/nonexistent/autoexec.cfg")) or not s.usable


# ---- discover: absent keys, a level already shown, companion keys -------------------------------

def _discover(env, answers):
    """Run interactive discover; each answer is (reply, edit) where edit(text) -> text simulates the game."""
    cfg = env["steam"]["eecfg"]
    it = iter(answers)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        reply, edit = next(it, ("q", None))
        if edit:
            cfg.write_text(edit(cfg.read_text()))
        return reply
    out = Out()
    args = argparse.Namespace(game="warframe", before=None, after=None, setting=None, label=None)
    cmd_discover(args, env["paths"], out, ask=ask)
    return out.text, asked


def _set(key, value):
    def edit(text):
        lines = [l for l in text.split("\n") if not l.startswith(key + "=")]
        i = lines.index("[Windows_Config,/EE/Types/Base/Config]")
        lines.insert(i + 1, f"{key}={value}")
        return "\n".join(lines)
    return edit


def test_discover_learns_native_upscaling_and_an_absent_key(env):
    answers = [
        ("", None), ("y", None),                                        # DLSS Quality: already shown in the menu
        ("", _set("Graphics.UpscaleMethod", "UM_REAL_OFF")),            # Off (native)
        ("", _set("Graphics.GeometryQuality", "GQ_LOW")),               # absent key appears
        ("", _set("Graphics.GeometryQuality", "GQ_MEDIUM")),
        ("", _set("Graphics.GeometryQuality", "GQ_HIGH")),
        ("", _set("Graphics.GeometryQuality", "GQ_LUDICROUS")),
    ] + [("s", None)] * 12
    text, asked = _discover(env, answers)
    learned = json.loads((env["data"] / "warframe.learned.json").read_text())
    assert learned["keys"]["upscaling"]["levels"] == ["UM_DLSS", "UM_REAL_OFF"]
    assert learned["keys"]["geometry"]["key"] == "Graphics.GeometryQuality"
    assert learned["section"] == "Windows_Config,/EE/Types/Base/Config"
    # both now join the search: native first, then DLSS Quality
    code, plan = run(["plan", "warframe", "--goal", "3840x2160@90"], env)
    assert "upscaling" not in plan.split("left out until")[1].split("\n")[0]
    assert "geometry" not in plan.split("left out until")[1].split("\n")[0]
    ad = Adapter.load("warframe")
    assert ad.setting("upscaling").values_for(1) == {"Graphics.UpscaleMethod": "UM_REAL_OFF"}


def test_discover_asks_a_skipped_level_again(env):
    # Low gives no change (the game did not write), the second pass catches it
    answers = [("s", None),                                             # skip upscaling
               ("", None),                                              # Low: nothing written (key absent, no question)
               ("", _set("Graphics.GeometryQuality", "GQ_MEDIUM")),
               ("", _set("Graphics.GeometryQuality", "GQ_HIGH")),
               ("", _set("Graphics.GeometryQuality", "GQ_LUDICROUS")),
               ("", _set("Graphics.GeometryQuality", "GQ_LOW"))] + [("s", None)] * 12
    text, asked = _discover(env, answers)
    assert "once more for Low" in text
    learned = json.loads((env["data"] / "warframe.learned.json").read_text())
    assert learned["keys"]["geometry"]["levels"] == ["GQ_LOW", "GQ_MEDIUM", "GQ_HIGH", "GQ_LUDICROUS"]


def test_discover_accepts_the_companion_key_changing_too(env):
    before = env["steam"]["eecfg"].parent / "before.cfg"
    after = env["steam"]["eecfg"].parent / "after.cfg"
    shutil.copy(PC_EECFG, before)
    after.write_text(PC_EECFG.read_text().replace("UpscaleMethod=UM_DLSS", "UpscaleMethod=UM_X")
                     .replace("Graphics.UpscaleQuality=UQ_QUALITY\n", ""))
    code, text = run(["discover", "warframe", "--before", str(before), "--after", str(after),
                      "--setting", "upscaling", "--label", "Off (native)"], env)
    assert code == 0, text
    assert '"Off (native)": "UM_X"' in text


# ---- 5. localconfig.vdf: a plain "230410" value before the apps/230410 block --------------------

BLOB = '"230410"\t\t"\x01\x02\\"bin\\\\ary\xff\xfe"'


def _localconfig_with_blob(steam, same_parent: bool) -> bytes:
    lc = steam["localconfig"]
    text = lc.read_text()
    if same_parent:
        text = text.replace('\t\t\t\t"apps"\n\t\t\t\t{\n', '\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t' + BLOB + "\n")
    else:
        text = text.replace('\t"Software"\n', '\t"apptickets"\n\t{\n\t\t' + BLOB + '\n\t}\n\t"Software"\n')
    data = text.encode("utf-8", errors="surrogateescape").replace("\xff\xfe".encode("utf-8"), b"\xff\xfe")
    lc.write_bytes(data)
    return data


@pytest.mark.parametrize("same_parent", [False, True])
def test_launch_options_skip_the_binary_230410_string(steam, same_parent):
    _localconfig_with_blob(steam, same_parent)
    st = Steam(steam["root"])
    assert st.get_launch_options(230410) == "gamescope -W 3840 -H 2160 -r 240 -f -- %command%"


@pytest.mark.parametrize("same_parent", [False, True])
def test_launch_options_write_keeps_the_blob_byte_for_byte(steam, tmp_path, same_parent):
    original = _localconfig_with_blob(steam, same_parent)
    st = Steam(steam["root"])
    old, new = st.launch_options_text(230410, "mangohud %command%")
    run_dir = RunDir(tmp_path / "runs", "r1").create()
    write_file(run_dir, steam["localconfig"], new, "launch options", [steam["root"]], min_ratio=0.9)
    got = steam["localconfig"].read_bytes()
    assert b"\x01\x02" in got and b"\xff\xfe" in got
    assert got == original.replace(b"gamescope -W 3840 -H 2160 -r 240 -f -- %command%", b"mangohud %command%")
    assert st.get_launch_options(230410) == "mangohud %command%"


def test_keyvalues_find_prefers_blocks_on_the_way_down():
    kv = KeyValues('"a"\n{\n\t"x"\t"plain"\n\t"x"\n\t{\n\t\t"k"\t"v"\n\t}\n}\n')
    assert kv.get(["a", "x", "k"]) == "v"
    assert kv.get(["a", "x"]) == "plain"           # the last step may be a value


def test_show_works_with_a_non_utf8_localconfig(env):
    _localconfig_with_blob(env["steam"], same_parent=False)
    code, text = run(["show", "warframe"], env)
    assert code == 0 and "gamescope -W 3840" in text


# ---- 4. kscreen-doctor -j ----------------------------------------------------------------------

def test_probe_runs_kscreen_doctor_j_first(monkeypatch, tmp_path):
    import gopt.hwprobe as hw
    calls = []

    def fake_run(cmd, timeout=5.0):
        calls.append(cmd)
        return (FIX / "kscreen_doctor_j.json").read_text() if cmd == ["kscreen-doctor", "-j"] else None
    monkeypatch.setattr(hw, "_run", fake_run)
    d = hw.display_info(drm_root=tmp_path)
    assert calls == [["kscreen-doctor", "-j"]] and d["source"] == "kscreen-doctor -j"
    by = {o["name"]: o for o in d["outputs"]}
    assert by["DP-2"]["active_mode"] == "3840x2160@240" and by["DP-2"]["scale"] == 1.5
    assert by["HDMI-A-1"]["active_mode"] == "2560x1440@144" and by["HDMI-A-1"]["scale"] == 1.0


def test_kscreen_json_fixture_has_the_pc_top_level_keys():
    doc = json.loads((FIX / "kscreen_doctor_j.json").read_text())
    assert set(doc) == {"features", "outputs", "screen", "tabletModeAvailable", "tabletModeEngaged"}
    dp = next(o for o in doc["outputs"] if o["name"] == "DP-2")
    assert dp["currentModeId"] == "34" and isinstance(dp["hdr"], bool)


def test_lg_max_mode_is_native_not_the_scaler_4k(monkeypatch, tmp_path):
    from gopt.hwprobe import parse_kscreen_json
    by = {o["name"]: o for o in parse_kscreen_json((FIX / "kscreen_doctor_j.json").read_text())}
    lg, dp = by["HDMI-A-1"], by["DP-2"]
    assert lg["max_mode"] == "2560x1440@144" and "3840x2160@59.94" in lg["scaler_modes"]
    assert dp["max_mode"] == "3840x2160@240" and dp["scaler_modes"] == []


# ---- 2. Proton Experimental 11, no GE-Proton ---------------------------------------------------

def test_proton_experimental_11_and_no_ge_proton(steam):
    root = steam["root"]
    (root / "steamapps" / "compatdata" / "230410" / "version").write_text("11.0-100\n")
    for d in ("Proton - Experimental", "Proton EasyAntiCheat Runtime"):
        (root / "steamapps" / "common" / d).mkdir(parents=True)
    (root / "compatibilitytools.d").mkdir()
    (root / "steamapps" / "common" / "Warframe" / "Warframe.x64.exe").write_bytes(b"MZ")
    st = Steam(root)
    assert st.proton_version(230410) == "11.0-100"
    app = st.app(230410)
    assert app.runtime == "proton" and app.compat_tool is None           # no CompatToolMapping entry
    assert "enables DXVK-NVAPI" in dlss_note(app.compat_tool or st.proton_version(230410))
    assert st.compat_tools() == {"valve": ["Proton - Experimental", "Proton EasyAntiCheat Runtime"], "custom": []}


def test_show_says_ge_proton_is_not_installed(env):
    (env["steam"]["root"] / "steamapps" / "compatdata" / "230410" / "version").write_text("11.0-100\n")
    (env["steam"]["root"] / "steamapps" / "common" / "Proton - Experimental").mkdir(parents=True)
    code, text = run(["show", "warframe"], env)
    assert "Proton prefix version: 11.0-100" in text
    assert "Proton - Experimental" in text and "GE-Proton is not installed" in text
