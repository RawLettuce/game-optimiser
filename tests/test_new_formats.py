"""Lossless round trips and targeted edits for the formats added for the new adapters (23 Oct 2026)."""

import json
from pathlib import Path

import pytest

from gopt.parsers.eecfg import EECfg, EECfgError
from gopt.parsers.jsontext import JsonText, JsonTextError
from gopt.parsers.srccfg import SrcCfg, SrcCfgError
from gopt.parsers.winreg import WinReg, WinRegError, unity_pref_name

FIX = Path(__file__).parent / "fixtures"


def raw(name):
    return (FIX / name).read_bytes().decode("utf-8")


def test_round_trips_are_byte_identical():
    for name, cls in (("autoexec.cfg", SrcCfg), ("brotato_save_v2.json", JsonText), ("user.reg", WinReg),
                      ("GameUserSettings.ini", EECfg)):
        t = raw(name)
        assert cls(t).text() == t, name


def test_srccfg_last_assignment_wins_and_edit_is_one_line():
    c = SrcCfg(raw("autoexec.cfg"))
    assert c.get("mat_picmip") == "1" and c.get("r_shadows") == "1" and c.get("cl_showfps") == "1"
    n = c.set("mat_picmip", "-1")
    old, new = c.text().splitlines(), n.text().splitlines()
    assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == [5] and new[5] == 'mat_picmip "-1"'
    n2 = n.set("mat_antialias", "4")
    assert n2.text().endswith('mat_antialias "4"\n') and n2.get("mat_antialias") == "4"
    assert c.set("cl_showfps", "0").text().splitlines()[4] == 'cl_showfps "0" // fps counter'
    with pytest.raises(SrcCfgError):
        c.set("bad key", "1")


def test_jsontext_edits_one_value_and_keeps_the_rest():
    j = JsonText(raw("brotato_save_v2.json"))
    assert j.get("settings.fullscreen") == "true" and j.get("progress.best_wave.brawler") == "14"
    assert j.get("progress.characters_unlocked.1") == "brawler"
    n = j.set("settings.fullscreen", "false")
    assert n.text() == raw("brotato_save_v2.json").replace('"fullscreen": true', '"fullscreen": false')
    assert json.loads(n.text())["progress"] == json.loads(raw("brotato_save_v2.json"))["progress"]
    assert JsonText(raw("brotato_save_v2.json")).set("settings.volume", "0.5").get("settings.volume") == "0.5"
    with pytest.raises(JsonTextError):
        j.set("settings.new_key", "1")              # never adds keys to a save file
    with pytest.raises(JsonTextError):
        j.set("settings.fullscreen", "maybe")       # keeps the JSON type
    with pytest.raises(JsonTextError):
        JsonText('{"a": 1')


def test_winreg_reads_unity_prefs_and_edits_a_dword_in_place():
    r = WinReg(raw("user.reg"))
    sec = "Software\\Ninja Kiwi\\BloonsTD6"
    assert r.get(f"{sec}::{unity_pref_name('Screenmanager Resolution Width')}") == "3840"
    assert r.get(f"{sec}::Screenmanager Resolution Height_h2627697771") == "2160"
    assert r.get("Software\\Wine\\Fonts::Name") == "Tahoma"
    n = r.set(f"{sec}::Screenmanager Fullscreen mode_h3630240806", "3")
    diff = [(a, b) for a, b in zip(r.text().splitlines(), n.text().splitlines()) if a != b]
    assert diff == [('"Screenmanager Fullscreen mode_h3630240806"=dword:00000001',
                     '"Screenmanager Fullscreen mode_h3630240806"=dword:00000003')]
    with pytest.raises(WinRegError):
        r.set(f"{sec}::unity.player_session_count_h922449978", "1")     # not a dword
    with pytest.raises(WinRegError):
        r.set(f"{sec}::Missing", "1")
    with pytest.raises(WinRegError):
        WinReg("not a registry\n")


def test_unity_pref_name_matches_known_names():
    assert unity_pref_name("Screenmanager Resolution Width") == "Screenmanager Resolution Width_h182942802"
    assert unity_pref_name("Screenmanager Fullscreen mode") == "Screenmanager Fullscreen mode_h3630240806"


def test_ue4_ini_keeps_crlf_and_edits_inside_the_named_section():
    c = EECfg(raw("GameUserSettings.ini"))
    assert c.newline == "\r\n" and c.get("sg.ShadowQuality", section="ScalabilityGroups") == "3"
    n = c.set("sg.ShadowQuality", "1", section="ScalabilityGroups")
    assert n.text() == raw("GameUserSettings.ini").replace("sg.ShadowQuality=3", "sg.ShadowQuality=1")
    with pytest.raises(EECfgError):
        c.set("x", "1", section="NoSuchSection")
