"""Generate the sample MangoHud CSV fixtures (deterministic). Run: python3 tests/fixtures/make_logs.py

Columns follow MangoHud src/logging.cpp. One file uses the log_versioning header, one does not.
"""

import random
from pathlib import Path

COLS = ("fps,frametime,cpu_load,cpu_power,gpu_load,cpu_temp,gpu_temp,gpu_core_clock,gpu_mem_clock,"
        "gpu_vram_used,gpu_power,ram_used,swap_used,process_rss,cpu_mhz,elapsed")
SYS_HDR = "os,cpu,gpu,ram,kernel,driver,cpuscheduler"
SYS_ROW = "Bazzite 44,AMD Ryzen 5 3600 6-Core Processor,NVIDIA GeForce RTX 3070,16GB,6.18.0,580.00,amd-pstate-epp"


def rows(seed, seconds, mean_ft, noise, gpu_load, cpu_load, vram_mb, spike_at=(), warmup_frames=60):
    """seconds of play at mean_ft ms per frame; spike_at are fractions of the run (0..1)."""
    rnd = random.Random(seed)
    n = int(seconds * 1000.0 / mean_ft)
    spike_idx = {int(f * n) for f in spike_at}
    elapsed = 0.0
    out = []
    for i in range(n):
        ft = rnd.gauss(mean_ft, mean_ft * noise)
        if i < warmup_frames:
            ft *= 2.5            # shader compile warm up, skipped by the metrics
        if i in spike_idx:
            ft = 80.0
        ft = max(1.0, ft)
        elapsed += ft * 1e6      # MangoHud elapsed is in ns in recent versions (unverified; ignored by the tool)
        out.append(f"{1000.0/ft:.2f},{ft:.3f},{cpu_load + rnd.uniform(-3, 3):.1f},65.0,{gpu_load + rnd.uniform(-2, 2):.1f},"
                   f"62,70,1900,7000,{vram_mb},210,9000,0,2500,4200,{int(elapsed)}")
    return out


def write(path, body, versioned):
    lines = []
    if versioned:
        lines += ["v1", "0.8.1", "---------------------SYSTEM INFO---------------------"]
    lines += [SYS_HDR, SYS_ROW]
    if versioned:
        lines += ["--------------------FRAME METRICS--------------------"]
    lines += [COLS] + body
    Path(path).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    here = Path(__file__).parent
    # Warframe: GPU bound at ~78 fps with two spikes, versioned header
    write(here / "mangohud_warframe_gpu_bound.csv",
          rows(1, 60, 12.8, 0.08, gpu_load=97, cpu_load=45, vram_mb=6900, spike_at=(0.5, 0.8)), True)
    # CS2: CPU bound at ~190 fps, no spikes, plain header
    write(here / "mangohud_cs2_cpu_bound.csv",
          rows(2, 60, 5.26, 0.10, gpu_load=55, cpu_load=92, vram_mb=4200), False)
    # CS2 meeting a 240 goal comfortably
    write(here / "mangohud_cs2_pass.csv",
          rows(3, 60, 3.7, 0.08, gpu_load=80, cpu_load=70, vram_mb=4000), True)
    # Warframe with a stutter storm (many spikes)
    write(here / "mangohud_warframe_spiky.csv",
          rows(4, 60, 9.5, 0.06, gpu_load=90, cpu_load=50, vram_mb=7600, spike_at=tuple(i / 100 for i in range(20, 100, 2))), True)
    # Launcher log: short, few rows (should be ignored by pick_log)
    write(here / "mangohud_launcher_short.csv",
          rows(5, 0.7, 16.7, 0.05, gpu_load=5, cpu_load=10, vram_mb=300, warmup_frames=0), False)
    print("written")
