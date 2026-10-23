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
