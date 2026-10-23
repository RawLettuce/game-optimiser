import json

from gopt.hwprobe import cpu_info, mem_info, gpu_info, parse_kscreen, fingerprint, update_cache, active_output

KSCREEN = """Output: 1 DP-2 enabled connected priority 1 DisplayPort Modes: 0:3840x2160@240*! 1:3840x2160@144 2:2560x1440@240 Geometry: 0,0 2560x1440 Scale: 1.5 Rotation: 1 Overscan: 0 Vrr: Automatic RgbRange: Automatic HDR: disabled Wide Color Gamut: disabled ICC profile: none Color profile source: sRGB Brightness control: unsupported Color power preference: Accuracy Color Powersaving tradeoff: None Sharpness: 0 Dimming: 100
Output: 2 HDMI-A-1 enabled connected priority 2 HDMI Modes: 0:2560x1440@144*! 1:1920x1080@60 Geometry: 2560,0 2560x1440 Scale: 1 Rotation: 1 Overscan: 0 Vrr: incapable RgbRange: Automatic HDR: incapable
"""


def test_cpu_and_mem_parsing():
    cpu = cpu_info("processor\t: 0\nmodel name\t: AMD Ryzen 5 3600 6-Core Processor\ncpu cores\t: 6\n\nprocessor\t: 1\nmodel name\t: AMD Ryzen 5 3600 6-Core Processor\ncpu cores\t: 6\n")
    assert cpu == {"model": "AMD Ryzen 5 3600 6-Core Processor", "cores": 6, "threads": 2}
    assert mem_info("MemTotal:       16318244 kB\nMemFree: 1 kB\n") == {"total_mb": 15935}


def test_gpu_parsing_with_bar1():
    out = "NVIDIA GeForce RTX 3070, 8192 MiB, 580.95.05, 00000000:0A:00.0\n"
    q = "    FB Memory Usage\n        Total : 8192 MiB\n    BAR1 Memory Usage\n        Total                             : 8192 MiB\n        Used : 10 MiB\n"
    g = gpu_info(out, q)
    assert g["name"] == "NVIDIA GeForce RTX 3070" and g["vram_mb"] == 8192 and g["driver"] == "580.95.05"
    assert g["bar1_mb"] == 8192 and g["resizable_bar"] is True
    g2 = gpu_info(out, "BAR1 Memory Usage\n        Total : 256 MiB\n")
    assert g2["resizable_bar"] is False
    assert gpu_info("", "")["vendor"] is None


def test_kscreen_parsing():
    outs = parse_kscreen(KSCREEN)
    assert [o["name"] for o in outs] == ["DP-2", "HDMI-A-1"]
    dp = outs[0]
    assert dp["active_mode"] == "3840x2160@240" and dp["scale"] == 1.5 and dp["refresh_hz"] == 240
    assert dp["hdr"] is False
    assert outs[1]["active_mode"] == "2560x1440@144"
    data = {"display": {"outputs": outs}}
    assert active_output(data, "DP-2") is dp
    assert active_output(data, "DP-9") is None


def test_cache_refreshes_only_on_fingerprint_change(tmp_path):
    cache = tmp_path / "hardware.json"
    data = {"probed_at": "t1", "gopt_version": "0", "gpu": {"driver": "580"}, "cpu": {"model": "x"}}
    fp, refreshed = update_cache(data, cache)
    assert refreshed and cache.exists()
    mtime = cache.stat().st_mtime
    data2 = dict(data, probed_at="t2")
    fp2, refreshed2 = update_cache(data2, cache)
    assert fp2 == fp and not refreshed2 and cache.stat().st_mtime == mtime
    data3 = dict(data, gpu={"driver": "585"})
    fp3, refreshed3 = update_cache(data3, cache)
    assert fp3 != fp and refreshed3
    prev = tmp_path / "hardware.prev.json"
    assert prev.exists() and json.loads(prev.read_text())["fingerprint"] == fp
    assert json.loads(cache.read_text())["fingerprint"] == fp3


def test_fingerprint_ignores_volatile_fields():
    a = {"probed_at": "1", "x": 1}
    b = {"probed_at": "2", "x": 1}
    assert fingerprint(a) == fingerprint(b)


# ---- regression: first PC run, 23 Oct 2026 (probe printed "gaming display DP-2: None") ----------

from pathlib import Path

from gopt.hwprobe import parse_kscreen_json, display_info, drm_connectors, edid_name

FIX = Path(__file__).parent / "fixtures"


def _check_pc_outputs(outs):
    by = {o["name"]: o for o in outs}
    assert set(by) == {"HDMI-A-1", "DP-2"}
    dp, lg = by["DP-2"], by["HDMI-A-1"]
    assert dp["active_mode"] == "3840x2160@240" and dp["refresh_hz"] == 240.0
    assert (dp["width"], dp["height"]) == (3840, 2160)
    assert dp["preferred_mode"] == "3840x2160@60" and dp["max_mode"] == "3840x2160@240"
    assert dp["scale"] == 1.5 and dp["hdr"] is True and dp["enabled"] is True and dp["priority"] == 1
    assert dp["pos"] == [2560, 0]
    assert lg["active_mode"] == "2560x1440@144" and lg["refresh_hz"] == 144.0
    assert lg["preferred_mode"] == "2560x1440@99.95"
    assert lg["scale"] == 1.0 and lg["hdr"] is False and lg["priority"] == 2 and lg["pos"] == [0, 0]
    # no duplicate WxH@Hz entries, largest first
    for o in outs:
        assert len(o["modes"]) == len(set(o["modes"]))
        assert o["modes"][0].startswith("3840x2160")


def test_kscreen_text_real_pc_output():
    _check_pc_outputs(parse_kscreen((FIX / "kscreen_doctor_o.txt").read_text()))


def test_kscreen_text_with_terminal_colours():
    # doctor.cpp colours the current mode as GREEN name '*' RESET and appends '!' after the reset
    text = (FIX / "kscreen_doctor_o.txt").read_text()
    g, cr = "\x1b[01;32m", "\x1b[0;0m"
    text = text.replace("Output: ", f"{g}Output: {cr}").replace("\tenabled", f"\t{g}enabled{cr}")
    text = text.replace("34:3840x2160@240.00*", f"34:{g}3840x2160@240.00*{cr}")
    text = text.replace("7:2560x1440@144.00*", f"7:{g}2560x1440@144.00*{cr}")
    _check_pc_outputs(parse_kscreen(text))


def test_kscreen_json_real_pc_shape():
    _check_pc_outputs(parse_kscreen_json((FIX / "kscreen_doctor_j.json").read_text()))


def test_kscreen_json_garbage_is_none():
    assert parse_kscreen_json("not json") is None
    assert parse_kscreen_json('{"outputs": "x"}') is None


def test_display_info_prefers_json_and_falls_back_to_text(tmp_path):
    j = (FIX / "kscreen_doctor_j.json").read_text()
    t = (FIX / "kscreen_doctor_o.txt").read_text()
    d = display_info(kscreen_json=j, kscreen_text="", drm_root=tmp_path)
    assert d["source"] == "kscreen-doctor -j" and len(d["outputs"]) == 2
    d = display_info(kscreen_json="{broken", kscreen_text=t, drm_root=tmp_path)
    assert d["source"] == "kscreen-doctor -o" and active_output({"display": d}, "DP-2")["active_mode"] == "3840x2160@240"


def _edid(name: str) -> bytes:
    e = bytearray(128)
    e[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    desc = bytearray(18)
    desc[3] = 0xFC
    desc[5:18] = (name.encode() + b"\n").ljust(13, b" ")
    e[72:90] = desc
    return bytes(e)


def test_drm_modes_deduped_with_preferred_first(tmp_path):
    lg = tmp_path / "card1-HDMI-A-1"
    lg.mkdir()
    (lg / "status").write_text("connected\n")
    # the kernel lists the preferred mode first, then one line per timing (duplicates by size)
    (lg / "modes").write_text("2560x1440\n3840x2160\n3840x2160\n3840x2160\n2560x1440\n2560x1440\n1920x1080\n1920x1080\n")
    (lg / "edid").write_bytes(_edid("LG ULTRAGEAR"))
    off = tmp_path / "card1-DP-1"
    off.mkdir()
    (off / "status").write_text("disconnected\n")
    drm = drm_connectors(tmp_path)
    assert drm == [{"connector": "HDMI-A-1", "monitor": "LG ULTRAGEAR", "preferred": "2560x1440",
                    "modes": ["2560x1440", "3840x2160", "1920x1080"], "above_preferred": ["3840x2160"]}]


def test_edid_name_handles_missing_and_short():
    assert edid_name(b"") is None
    assert edid_name(_edid("AG276UZD")) == "AG276UZD"


def test_cli_probe_prints_the_gaming_display(tmp_path, monkeypatch):
    from gopt import cli, hwprobe
    from gopt.paths import Paths
    disp = display_info(kscreen_json=(FIX / "kscreen_doctor_j.json").read_text(), kscreen_text="", drm_root=tmp_path)
    monkeypatch.setattr(hwprobe, "probe", lambda: {"display": disp, "gpu": {}, "cpu": {}})
    lines = []
    assert cli.main(["probe"], out=lines.append, paths=Paths(tmp_path)) == 0
    line = [l for l in lines if l.startswith("gaming display")][0]
    assert "3840x2160@240" in line and "None" not in line and "native 3840x2160@60" in line
