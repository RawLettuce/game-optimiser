import json
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.adapters import Adapter, DATA_DIR
from gopt.steam import Steam


def test_both_adapters_load_and_are_consistent():
    assert Adapter.available() == ["cs2", "warframe"]
    for game in Adapter.available():
        ad = Adapter.load(game)
        assert ad.settings, game
        for s in ad.settings:
            assert len(s.levels) == len(s.labels) == len(s.cost), s.id
            assert s.cost[0] == 1.0 and all(b >= a for a, b in zip(s.cost, s.cost[1:])), s.id
            assert s.status in ("P", "S", "V", "U")
            if s.vram_mb:
                assert len(s.vram_mb) == len(s.levels)
        assert "%command%" not in (ad.launch_prefix or "")
        assert ad.benchmark["instructions"].strip()


def test_unknown_adapter_refuses():
    with pytest.raises(Refusal):
        Adapter.load("elden_ring")


def test_warframe_paths_and_read(steam):
    s = Steam(steam["root"])
    ad = Adapter.load("warframe")
    p = ad.settings_path(s)
    assert p == steam["eecfg"]
    vals = ad.read_settings(p)
    assert vals["Graphics.ShadowQuality"] == "SQ_HIGH"
    assert vals["Graphics.GpuParticles"] is None
    levels = ad.current_levels(vals)
    assert levels["shadows"] == 2 and levels["textures"] == 0 and levels["gpu_particles"] is None
    auto, manual = ad.override_changes(vals)
    assert auto == {"Graphics.AutoDetectGraphicsSettings": "0"}
    assert {o.key for o in manual} == {"Graphics.MaxFramerate", "Graphics.VSync"}


def test_cs2_paths_and_read(steam):
    s = Steam(steam["root"])
    ad = Adapter.load("cs2")
    p = ad.settings_path(s)
    assert p == steam["cs2_video"]
    vals = ad.read_settings(p)
    assert vals["setting.videocfg_shadow_quality"] == "3"
    levels = ad.current_levels(vals)
    assert levels["shadows"] == 3 and levels["msaa"] == 2 and levels["fsr"] == 4
    auto, manual = ad.override_changes(vals)
    assert auto == {} and manual == []


def test_changes_for_rung_and_apply(steam):
    s = Steam(steam["root"])
    ad = Adapter.load("cs2")
    p = ad.settings_path(s)
    vals = ad.read_settings(p)
    rung = {x.id: 0 for x in ad.settings}
    changes = ad.changes_for_rung(rung, vals)
    assert changes["setting.videocfg_shadow_quality"] == "0"
    assert changes["setting.msaa_samples"] == "0"
    assert "setting.videocfg_fsr_detail" in changes       # level 0 is FSR Performance ("4")
    doc = ad.apply_changes(ad.load_doc(p), changes)
    text = ad.doc_text(doc)
    assert '"setting.videocfg_shadow_quality"\t\t"0"' in text
    assert text.count("\n") == p.read_text().count("\n")


def test_warframe_apply_adds_missing_keys(steam):
    s = Steam(steam["root"])
    ad = Adapter.load("warframe")
    p = ad.settings_path(s)
    vals = ad.read_settings(p)
    rung = {x.id: x.top for x in ad.settings}
    changes = ad.changes_for_rung(rung, vals)
    doc = ad.apply_changes(ad.load_doc(p), changes)
    text = ad.doc_text(doc)
    assert "Graphics.GpuParticles=GPQ_LUDICROUS" in text
    assert "Graphics.ShadowQuality=SQ_LUDICROUS" in text
    assert text.index("Graphics.GpuParticles") < text.index("[Launcher,")


def test_missing_prefix_refuses(tmp_path, steam):
    import shutil
    shutil.rmtree(steam["root"] / "steamapps" / "compatdata")
    s = Steam(steam["root"])
    with pytest.raises(Refusal):
        Adapter.load("warframe").settings_path(s)


def test_learned_overrides_keys_and_costs(tmp_path):
    import shutil
    d = tmp_path / "adapters"
    d.mkdir()
    shutil.copy(DATA_DIR / "warframe.toml", d / "warframe.toml")
    (d / "warframe.learned.json").write_text(json.dumps({
        "keys": {"gpu_particles": {"key": "Graphics.GPUParticlesQuality", "levels": ["GPQ_OFF", "GPQ_LOW", "GPQ_MED", "GPQ_HIGH", "GPQ_LUD"]}},
        "costs": {"shadows": [1.0, 1.02, 1.04, 1.3]},
        "headroom": 1.1,
        "override_keys": {"Graphics.MaxFramerate": "Graphics.FrameRateLimit"},
    }))
    ad = Adapter.load("warframe", d)
    gp = ad.setting("gpu_particles")
    assert gp.key == "Graphics.GPUParticlesQuality" and gp.levels[0] == "GPQ_OFF" and gp.status == "V"
    assert ad.setting("shadows").cost == [1.0, 1.02, 1.04, 1.3]
    assert ad.headroom == 1.1
    fr = [o for o in ad.overrides if o.key == "Graphics.FrameRateLimit"]
    assert fr and fr[0].status == "V"
