"""Frame metrics from MangoHud rows: averages, lows, spikes, bound classification.

Definitions (DESIGN.md 8.3):
- average fps = 1000 / mean(frametime ms)
- 1% low (average) = 1000 / mean of the slowest 1% of frames (CapFrameX "x% low average")
- 1% low (integral) = fps value the run stayed below for 1% of total time (CapFrameX "x% low integral")
- spike = frame longer than max(2 x median, median + 10 ms)
Elapsed time is the cumulative sum of frametimes; the elapsed column is ignored.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, asdict


@dataclass
class Metrics:
    frames: int
    duration_s: float
    avg_fps: float
    low1_avg_fps: float
    low1_integral_fps: float
    low01_avg_fps: float
    p1_fps: float
    median_frametime_ms: float
    max_frametime_ms: float
    spikes: int
    spikes_per_min: float
    median_gpu_load: float | None
    median_cpu_load: float | None
    max_vram_mb: float | None
    half_split_diff: float   # |avg first half - avg second half| / avg, the noise estimate

    def as_dict(self):
        return asdict(self)


def _slowest_mean_fps(ft_desc: list[float], fraction: float) -> float:
    n = max(1, math.ceil(len(ft_desc) * fraction))
    return 1000.0 / (sum(ft_desc[:n]) / n)


def _integral_low_fps(ft_desc: list[float], fraction: float) -> float:
    total = sum(ft_desc)
    acc = 0.0
    for ft in ft_desc:
        acc += ft
        if acc >= total * fraction:
            return 1000.0 / ft
    return 1000.0 / ft_desc[-1]


def compute(rows: list[dict], skip_s: float = 10.0) -> Metrics:
    ft_all = [r["frametime"] for r in rows if isinstance(r.get("frametime"), float) and r["frametime"] > 0]
    if len(ft_all) < 10:
        raise ValueError("too few frames")
    # skip the warm up: cumulative frametime below skip_s
    acc, start = 0.0, 0
    for i, ft in enumerate(ft_all):
        if acc >= skip_s * 1000.0:
            start = i
            break
        acc += ft
    else:
        start = 0
    if len(ft_all) - start < 10:
        start = 0
    kept = rows[-len(ft_all):][start:] if len(rows) == len(ft_all) else [r for r in rows if isinstance(r.get("frametime"), float) and r["frametime"] > 0][start:]
    ft = [r["frametime"] for r in kept]
    duration = sum(ft) / 1000.0
    avg_fps = 1000.0 / (sum(ft) / len(ft))
    desc = sorted(ft, reverse=True)
    med = statistics.median(ft)
    thr = max(2.0 * med, med + 10.0)
    spikes = sum(1 for x in ft if x > thr)
    p1_ft = desc[max(0, min(len(desc) - 1, math.floor(len(desc) * 0.01)))]
    half = len(ft) // 2
    a1 = 1000.0 / (sum(ft[:half]) / half) if half else avg_fps
    a2 = 1000.0 / (sum(ft[half:]) / (len(ft) - half)) if len(ft) - half else avg_fps

    def med_col(name):
        vals = [r[name] for r in kept if isinstance(r.get(name), float)]
        return statistics.median(vals) if vals else None

    def max_col(name):
        vals = [r[name] for r in kept if isinstance(r.get(name), float)]
        return max(vals) if vals else None

    return Metrics(
        frames=len(ft), duration_s=round(duration, 2), avg_fps=round(avg_fps, 1),
        low1_avg_fps=round(_slowest_mean_fps(desc, 0.01), 1),
        low1_integral_fps=round(_integral_low_fps(desc, 0.01), 1),
        low01_avg_fps=round(_slowest_mean_fps(desc, 0.001), 1),
        p1_fps=round(1000.0 / p1_ft, 1), median_frametime_ms=round(med, 3), max_frametime_ms=round(max(ft), 2),
        spikes=spikes, spikes_per_min=round(spikes / duration * 60.0, 2) if duration else 0.0,
        median_gpu_load=med_col("gpu_load"), median_cpu_load=med_col("cpu_load"), max_vram_mb=max_col("gpu_vram_used"),
        half_split_diff=round(abs(a1 - a2) / avg_fps, 4) if avg_fps else 0.0)


def classify_bound(m: Metrics, goal_fps: float) -> str:
    """'gpu', 'cpu', 'met' (goal already reached) or 'unknown' (no load columns or neither saturated)."""
    if m.avg_fps >= goal_fps:
        return "met"
    if m.median_gpu_load is None:
        return "unknown"
    if m.median_gpu_load >= 85.0:
        return "gpu"
    if m.median_cpu_load is not None and m.median_gpu_load < 70.0:
        return "cpu"
    return "unknown"


def passes(m: Metrics, goal_fps: float, low_ratio: float = 0.75, max_spikes_per_min: float = 3.0) -> tuple[bool, list[str]]:
    reasons = []
    if m.avg_fps < goal_fps:
        reasons.append(f"average {m.avg_fps} < goal {goal_fps}")
    if m.low1_avg_fps < goal_fps * low_ratio:
        reasons.append(f"1% low {m.low1_avg_fps} < {round(goal_fps * low_ratio, 1)}")
    if m.spikes_per_min > max_spikes_per_min:
        reasons.append(f"{m.spikes_per_min} spikes/min > {max_spikes_per_min}")
    return (not reasons), reasons
