import shutil
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.mangohud import parse_log, config_text, app_config_path, find_logs, pick_log, wait_for_log
from gopt.metrics import compute, classify_bound, passes, Metrics

FIX = Path(__file__).parent / "fixtures"


def test_parse_versioned_and_plain_logs():
    v = parse_log(FIX / "mangohud_warframe_gpu_bound.csv")
    assert v["sysinfo"]["gpu"] == "NVIDIA GeForce RTX 3070"
    assert v["columns"][:2] == ["fps", "frametime"]
    assert len(v["rows"]) == 4687          # 60 s at 12.8 ms
    p = parse_log(FIX / "mangohud_cs2_cpu_bound.csv")
    assert p["sysinfo"]["cpu"].startswith("AMD Ryzen 5 3600")
    assert len(p["rows"]) == 11406         # 60 s at 5.26 ms


def test_parse_rejects_garbage(tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("hello\nworld\n")
    with pytest.raises(Refusal):
        parse_log(bad)
    short = tmp_path / "s.csv"
    short.write_text("fps,frametime\n60,16.6\n")
    with pytest.raises(Refusal):
        parse_log(short)


def test_metrics_hand_computed():
    # 20 frames: eighteen at 10 ms, one 30 ms, one 50 ms. No warm up skip.
    ft = [10.0] * 18 + [30.0, 50.0]
    rows = [{"fps": 1000 / x, "frametime": x, "gpu_load": 90.0, "cpu_load": 40.0, "gpu_vram_used": 5000.0} for x in ft]
    m = compute(rows, skip_s=0)
    assert m.frames == 20
    assert m.avg_fps == round(1000 / (sum(ft) / 20), 1)          # 1000/13 = 76.9
    assert m.low1_avg_fps == 20.0                                  # slowest 1% of 20 frames = 1 frame = 50 ms
    assert m.low01_avg_fps == 20.0
    # integral: total 260 ms, 1% = 2.6 ms, first frame (50 ms) already covers it -> 20 fps
    assert m.low1_integral_fps == 20.0
    assert m.median_frametime_ms == 10.0
    # spike threshold = max(20, 20) = 20 ms -> 30 and 50 are spikes
    assert m.spikes == 2
    assert m.median_gpu_load == 90.0 and m.max_vram_mb == 5000.0
    assert classify_bound(m, 90) == "gpu"
    assert classify_bound(m, 60) == "met"


def test_integral_low_differs_from_average_low():
    ft = [10.0] * 980 + [20.0] * 20   # 2% of frames are slow
    rows = [{"frametime": x} for x in ft]
    m = compute(rows, skip_s=0)
    assert m.low1_avg_fps == 50.0            # slowest 1% = 10 frames at 20 ms
    assert m.low1_integral_fps == 50.0       # time below 50 fps = 400 ms of 10200 ms = 3.9% >= 1%
    ft2 = [10.0] * 999 + [20.0]
    m2 = compute([{"frametime": x} for x in ft2], skip_s=0)
    # ceil(1000*0.01)=10 frames: one 20 ms + nine 10 ms -> mean 11 ms -> 90.9 fps
    assert m2.low1_avg_fps == 90.9
    # integral: 20 ms of 10010 ms is 0.2% < 1%, so the run was "below 100 fps" for less than 1% of the time
    assert m2.low1_integral_fps == 100.0


def test_fixture_logs_classify_as_designed():
    wf = compute(parse_log(FIX / "mangohud_warframe_gpu_bound.csv")["rows"])
    assert 70 < wf.avg_fps < 86
    assert wf.spikes == 2
    assert classify_bound(wf, 90) == "gpu"
    ok, why = passes(wf, 90)
    assert not ok and "average" in why[0]
    cs = compute(parse_log(FIX / "mangohud_cs2_cpu_bound.csv")["rows"])
    assert classify_bound(cs, 240) == "cpu"
    cs_pass = compute(parse_log(FIX / "mangohud_cs2_pass.csv")["rows"])
    assert passes(cs_pass, 240)[0]
    spiky = compute(parse_log(FIX / "mangohud_warframe_spiky.csv")["rows"])
    assert spiky.spikes_per_min > 3
    assert not passes(spiky, 90)[0]


def test_warmup_is_skipped():
    rows = parse_log(FIX / "mangohud_warframe_gpu_bound.csv")["rows"]
    with_skip = compute(rows, skip_s=10)
    without = compute(rows, skip_s=0)
    assert with_skip.frames < without.frames
    assert with_skip.avg_fps > without.avg_fps


def test_config_text_and_app_config_path(tmp_path):
    txt = config_text(tmp_path / "logs", 60)
    assert "output_folder=" in txt and "log_duration=60" in txt and "log_interval=50" in txt and "no_display" in txt
    assert app_config_path(tmp_path, "Warframe.x64.exe", True) == tmp_path / "wine-Warframe.x64.conf"
    assert app_config_path(tmp_path, "cs2", False) == tmp_path / "cs2.conf"


def test_find_and_pick_log_prefers_the_game_over_the_launcher(tmp_path):
    shutil.copy(FIX / "mangohud_launcher_short.csv", tmp_path / "Launcher_2026-10-23_18-00-00.csv")
    shutil.copy(FIX / "mangohud_warframe_gpu_bound.csv", tmp_path / "Warframe.x64_2026-10-23_18-00-05.csv")
    (tmp_path / "Warframe.x64_2026-10-23_18-00-05_summary.csv").write_text("x\n")
    logs = find_logs(tmp_path)
    assert len(logs) == 2
    assert pick_log(logs).name.startswith("Warframe.x64")
    assert [p.name for p in find_logs(tmp_path, "Warframe.x64.exe")] == ["Warframe.x64_2026-10-23_18-00-05.csv"]


def test_wait_for_log_returns_when_file_stops_growing(tmp_path):
    clock = {"t": 1000.0}
    target = tmp_path / "cs2_2026-10-23_18-00-00.csv"
    writes = iter([b"fps,frametime\n", b"60,16\n" * 20, b"", b"", b""])

    def fake_sleep(s):
        clock["t"] += s
        chunk = next(writes, b"")
        if chunk:
            with open(target, "ab") as f:
                f.write(chunk)

    p = wait_for_log(tmp_path, "cs2", since=0, quiet_s=2, timeout_s=60, poll_s=1,
                     sleep=fake_sleep, clock=lambda: clock["t"])
    assert p == target


def test_wait_for_log_times_out(tmp_path):
    clock = {"t": 0.0}

    def fake_sleep(s):
        clock["t"] += s

    with pytest.raises(Refusal):
        wait_for_log(tmp_path, None, since=0, quiet_s=1, timeout_s=5, poll_s=1, sleep=fake_sleep, clock=lambda: clock["t"])
