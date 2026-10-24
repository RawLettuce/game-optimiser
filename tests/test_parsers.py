from pathlib import Path

import pytest

from gopt.parsers.keyvalues import KeyValues, KeyValuesError, diff_paths
from gopt.parsers.eecfg import EECfg, EECfgError

FIX = Path(__file__).parent / "fixtures"


# ---------------- KeyValues -----------------

@pytest.mark.parametrize("name", ["cs2_video.txt", "localconfig.vdf", "loginusers.vdf",
                                  "libraryfolders.vdf", "appmanifest_230410.acf"])
def test_keyvalues_round_trip_is_byte_identical(name):
    text = (FIX / name).read_bytes().decode("utf-8")
    kv = KeyValues(text)
    assert kv.text == text
    assert kv.roots, "parsed nothing"


def test_keyvalues_reads_nested_values():
    kv = KeyValues.load(FIX / "localconfig.vdf")
    assert kv.get(["UserLocalConfigStore", "Software", "Valve", "Steam", "apps", "230410", "LaunchOptions"]) \
        == "gamescope -W 3840 -H 2160 -r 240 -f -- %command%"
    assert kv.get(["userlocalconfigstore", "software", "valve", "steam", "apps", "730", "LaunchOptions"]) is None
    assert kv.get(["UserLocalConfigStore", "system", "EnableGameOverlay"]) == "1"


def test_keyvalues_set_existing_value_changes_one_line_only():
    text = (FIX / "cs2_video.txt").read_bytes().decode("utf-8")
    kv = KeyValues(text)
    new = kv.set(["video.cfg", "setting.videocfg_shadow_quality"], "1")
    a, b = text.splitlines(), new.text.splitlines()
    assert len(a) == len(b)
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    assert len(changed) == 1
    assert '"setting.videocfg_shadow_quality"\t\t"1"' in b[changed[0]]
    assert diff_paths(kv.to_obj(), new.to_obj()) == [("video.cfg", "setting.videocfg_shadow_quality")]


def test_keyvalues_add_missing_key_into_block_keeps_indentation():
    kv = KeyValues.load(FIX / "localconfig.vdf")
    path = ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps", "730", "LaunchOptions"]
    new = kv.set(path, "mangohud %command%")
    assert new.get(path) == "mangohud %command%"
    assert diff_paths(kv.to_obj(), new.to_obj()) == [tuple(path)]
    line = [l for l in new.text.splitlines() if "mangohud %command%" in l][0]
    assert line.startswith("\t\t\t\t\t\t\"LaunchOptions\"")
    assert len(new.text.splitlines()) == len(kv.text.splitlines()) + 1


def test_keyvalues_escapes_quotes_in_values():
    kv = KeyValues('"a"\n{\n\t"b"\t\t"x"\n}\n')
    new = kv.set(["a", "b"], 'say "hi"')
    assert new.get(["a", "b"]) == 'say "hi"'
    assert KeyValues(new.text).get(["a", "b"]) == 'say "hi"'


def test_keyvalues_rejects_unbalanced():
    with pytest.raises(KeyValuesError):
        KeyValues('"a"\n{\n\t"b"\t"c"\n')
    with pytest.raises(KeyValuesError):
        KeyValues('"a" "b" }')


def test_keyvalues_ignores_comments_and_conditionals():
    kv = KeyValues('// comment\n"a"\n{\n\t"b"\t"c" [$WIN32]\n\t"d"\t"e"\n}\n')
    assert kv.get(["a", "b"]) == "c"
    assert kv.get(["a", "d"]) == "e"


# ---------------- EE.cfg -----------------

def test_eecfg_round_trip_is_byte_identical():
    text = (FIX / "EE.cfg").read_bytes().decode("utf-8")
    cfg = EECfg(text)
    assert cfg.text() == text


def test_eecfg_round_trip_crlf_and_bom():
    text = "﻿[A,/EE/Types/Base/Config]\r\nGraphics.X=1\r\n\r\n[B]\r\nk=v\r\n"
    cfg = EECfg(text)
    assert cfg.text() == text
    assert cfg.set("Graphics.X", "2").text() == text.replace("Graphics.X=1", "Graphics.X=2")


def test_eecfg_reads_sections_and_keys():
    cfg = EECfg.load(FIX / "EE.cfg")
    assert cfg.section_names() == ["KeyBindings,/EE/Types/Input/KeyBindings",
                                   "Windows_Config,/EE/Types/Base/Config",
                                   "Launcher,/EE/Types/Base/LauncherConfig"]
    assert cfg.get("Graphics.ShadowQuality") == "SQ_HIGH"
    assert cfg.get("Graphics.Brightness") == "0.9"
    assert cfg.graphics_section().header == "Windows_Config,/EE/Types/Base/Config"


def test_eecfg_set_existing_key_changes_one_line():
    cfg = EECfg.load(FIX / "EE.cfg")
    new = cfg.set("Graphics.ShadowQuality", "SQ_LOW")
    a, b = cfg.text().splitlines(), new.text().splitlines()
    assert len(a) == len(b)
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    assert changed and len(changed) == 1
    assert b[changed[0]] == "Graphics.ShadowQuality=SQ_LOW"


def test_eecfg_adds_missing_key_to_graphics_section():
    cfg = EECfg.load(FIX / "EE.cfg")
    new = cfg.set("Graphics.GpuParticles", "GPQ_MEDIUM")
    assert new.get("Graphics.GpuParticles") == "GPQ_MEDIUM"
    sec = new.graphics_section()
    assert "Graphics.GpuParticles" in sec.keys
    # inserted inside the graphics section, before the next header
    lines = new.text().splitlines()
    idx = lines.index("Graphics.GpuParticles=GPQ_MEDIUM")
    assert idx < lines.index("[Launcher,/EE/Types/Base/LauncherConfig]")
    assert len(lines) == len(cfg.text().splitlines()) + 1


def test_eecfg_graphics_section_fallback_to_config_header():
    cfg = EECfg("[KeyBindings,/EE/Types/Input/KeyBindings]\nA=B\n\n[Windows_Config,/EE/Types/Base/Config]\nAudio.X=1\n")
    assert cfg.graphics_section().header == "Windows_Config,/EE/Types/Base/Config"
    assert cfg.set("Graphics.Y", "2").get("Graphics.Y") == "2"


def test_eecfg_refuses_without_a_graphics_section():
    cfg = EECfg("[KeyBindings,/EE/Types/Input/KeyBindings]\nA=B\n")
    with pytest.raises(EECfgError):
        cfg.set("Graphics.Y", "2")
