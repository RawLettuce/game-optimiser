"""Quality ladder and the measure and adjust search (DESIGN.md section 8).

The ladder is a total order of rungs from lowest to highest quality. The
search is bisection over the ladder with a model predicted starting point.
Measured pass or fail decides; the model only chooses where to probe next.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .adapters import Adapter, Setting
from .metrics import Metrics, classify_bound, passes
from .model import CostModel, Rung


# ---------------------------------------------------------------- ladder

def build_ladder(settings: list[Setting], pins: dict[str, int] | None = None,
                 no_upscaling: bool = False, vram_cap_mb: float | None = None) -> list[Rung]:
    """Greedy: raise the setting with the best visual value per log frametime cost, one step at a time."""
    pins = dict(pins or {})
    if no_upscaling:
        for s in settings:
            if s.upscaling:
                pins.setdefault(s.id, s.top)       # top level of an upscaling setting is 'off'
    cur: Rung = {}
    for s in settings:
        if s.id in pins:
            cur[s.id] = pins[s.id]
        else:
            cur[s.id] = 0
    ladder = [dict(cur)]
    while True:
        best, best_ratio = None, -1.0
        for s in settings:
            if s.id in pins:
                continue
            lv = cur[s.id]
            if lv >= s.top:
                continue
            if vram_cap_mb and s.vram_mb and s.vram_mb[lv + 1] > vram_cap_mb:
                continue
            gain = s.visual / max(1, s.top)
            cost = math.log(max(1.0001, s.cost[lv + 1] / s.cost[lv]))
            ratio = gain / cost
            if ratio > best_ratio:
                best, best_ratio = s, ratio
        if best is None:
            break
        cur[best.id] += 1
        ladder.append(dict(cur))
    return ladder


def build_phases(settings: list[Setting], pins: dict[str, int] | None = None, no_upscaling: bool = False,
                 vram_cap_mb: float | None = None) -> list[dict]:
    """Native first (Matthew's rule, 23 Oct 2026): the upscaler is pinned Off for the first ladder; a
    second ladder with the upscaler pinned at its `fallback` level (DLSS Quality) is only searched when
    no native rung reaches the goal. Without an unpinned upscaler with a fallback there is one phase."""
    pins = dict(pins or {})
    ups = [s for s in settings if s.upscaling and s.id not in pins]
    if no_upscaling or not ups or not all(s.fallback for s in ups):
        return [{"name": "native" if no_upscaling else "all settings",
                 "ladder": build_ladder(settings, pins, no_upscaling, vram_cap_mb)}]
    native = dict(pins, **{s.id: s.top for s in ups})
    fb = dict(pins)
    names = []
    for s in ups:
        lv = s.level_of(s.fallback)
        if lv is None:
            raise ValueError(f"{s.id}: fallback {s.fallback!r} is not one of its levels")
        fb[s.id] = lv
        names.append(s.labels[lv])
    return [{"name": "native", "ladder": build_ladder(settings, native, False, vram_cap_mb)},
            {"name": " + ".join(names), "ladder": build_ladder(settings, fb, False, vram_cap_mb)}]


def predicted_start(model, ladder: list[Rung], target_fps: float) -> int:
    """Highest rung the model predicts at or above the target, else the lowest rung."""
    if model is None or model.scale is None:
        return 0
    for idx in range(len(ladder) - 1, -1, -1):
        fps = model.predict_fps(ladder[idx])
        if fps is not None and fps >= target_fps:
            return idx
    return 0


def describe_rung(adapter: Adapter, rung: Rung) -> str:
    parts = []
    for s in adapter.settings:
        if s.id in rung:
            parts.append(f"{s.label}={s.labels[rung[s.id]]}")
    return ", ".join(parts)


def nearest_rung(ladder: list[Rung], levels: dict[str, int | None]) -> int:
    """Index of the ladder rung closest to a set of current levels (unknown levels ignored)."""
    best, best_d = 0, None
    for i, r in enumerate(ladder):
        d = sum(abs(r[k] - v) for k, v in levels.items() if v is not None and k in r)
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


# ---------------------------------------------------------------- search

@dataclass
class RunResult:
    rung_idx: int
    metrics: Metrics
    passed: bool
    reasons: list[str]
    confirm: bool = False


@dataclass
class Search:
    adapter: Adapter
    ladder: list[Rung]
    goal_fps: float
    start_idx: int
    low_ratio: float = 0.75
    max_runs: int = 6
    margin_min: float = 0.05
    headroom: float | None = None
    results: list[RunResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model: CostModel | None = None
    bound: str = "unknown"
    margin: float = 0.05
    finished: bool = False
    stepped_down: bool = False
    _confirm_pending: int | None = None

    def __post_init__(self):
        if self.headroom is None:
            self.headroom = self.adapter.headroom
        if self.model is None:          # a later phase passes the earlier phase's calibrated model
            self.model = CostModel(self.adapter.settings, dict(self.ladder[self.start_idx]))

    # ---- state helpers ------------------------------------------------
    @property
    def top(self) -> int:
        return len(self.ladder) - 1

    def _measured(self, idx: int) -> list[RunResult]:
        return [r for r in self.results if r.rung_idx == idx]

    def highest_pass(self) -> int:
        ps = [r.rung_idx for r in self.results if r.passed]
        return max(ps) if ps else -1

    def lowest_fail(self) -> int:
        fs = [r.rung_idx for r in self.results if not r.passed]
        return min(fs) if fs else self.top + 1

    def inversions(self) -> list[tuple[int, int]]:
        out = []
        for a in self.results:
            for b in self.results:
                if a.passed and not b.passed and a.rung_idx > b.rung_idx:
                    out.append((a.rung_idx, b.rung_idx))
        return out

    def best(self) -> int | None:
        """Highest rung measured as passing, below the lowest measured failure when there is an inversion."""
        inv = self.inversions()
        if inv:
            lowest_fail = min(b for _, b in inv)
            ps = [r.rung_idx for r in self.results if r.passed and r.rung_idx < lowest_fail]
            return max(ps) if ps else None
        ps = [r.rung_idx for r in self.results if r.passed]
        return max(ps) if ps else None

    def target_fps(self) -> float:
        return self.goal_fps * self.headroom * (1.0 + self.margin)

    # ---- the loop -----------------------------------------------------
    def next_rung(self) -> int | None:
        """Rung index to measure next, or None when the search is finished."""
        if self.finished:
            return None
        if len(self.results) >= self.max_runs:
            self.notes.append(f"run budget of {self.max_runs} used")
            self.finished = True
            return None
        if not self.results:
            return self.start_idx
        if self._confirm_pending is not None:
            return self._confirm_pending
        if self.inversions():
            self.notes.append("inversion (a higher rung passed while a lower failed): preferring the lower rung")
            self.finished = True
            return None
        # Monotone ladder: every rung below a pass passes, every rung above a fail fails.
        hp, lf = self.highest_pass(), self.lowest_fail()
        if lf == 0:
            self.notes.append("the lowest rung fails: goal not reachable with graphics settings")
            self.finished = True
            return None
        if hp >= 0 and lf - hp <= self.resolution:
            # the answer is pinned down to within `resolution` rungs: confirm the best pass if needed
            return self._maybe_confirm(hp)
        return self._predicted_candidate(lo=hp, hi=lf)

    resolution: int = 2   # stop when fewer than this many unmeasured rungs separate the best pass from the lowest fail

    def _maybe_confirm(self, idx: int) -> int | None:
        runs = self._measured(idx)
        if any(r.confirm for r in runs) or len(runs) >= 2:
            self.finished = True
            return None
        # a pass with a margin of at least twice the noise estimate needs no second run
        m = runs[-1].metrics
        comfortable = m.avg_fps >= self.goal_fps * self.headroom * (1.0 + 2.0 * self.margin) \
            and m.low1_avg_fps >= self.goal_fps * self.headroom * self.low_ratio * (1.0 + self.margin) \
            and m.spikes_per_min <= 1.0
        if comfortable:
            self.notes.append(f"rung {idx} passed with a comfortable margin: no confirmation run needed")
            self.finished = True
            return None
        self._confirm_pending = idx
        return idx

    def _predicted_candidate(self, lo: int, hi: int) -> int | None:
        """Highest rung strictly inside (lo, hi) predicted to reach the target, kept in the middle half of the bracket."""
        if hi - lo <= 1:
            return None
        target = self.target_fps()
        cand = None
        for idx in range(hi - 1, lo, -1):
            fps = self.model.predict_fps(self.ladder[idx]) if self.model else None
            if fps is not None and fps >= target:
                cand = idx
                break
        if cand is None:
            if lo < 0 and self.model is not None and self.model.scale is not None:
                # nothing is predicted to pass: measure the bottom rung now, so an unreachable goal costs one
                # run instead of a bisection (and the next phase, e.g. DLSS Quality, gets the budget)
                return 0
            cand = (lo + hi) // 2
        # the model can be wrong at first: keep every probe inside the middle half of the open bracket so the
        # bracket shrinks by at least a quarter per run, like bisection, while a good model still steers it
        width = hi - lo
        if width >= 4:
            lo_c, hi_c = lo + max(1, width // 4), hi - max(1, width // 4)
            cand = max(lo_c, min(hi_c, cand))
        cand = max(lo + 1, min(hi - 1, cand))
        return cand

    def record(self, idx: int, m: Metrics) -> RunResult:
        confirm = self._confirm_pending == idx
        ok, reasons = passes(m, self.goal_fps * self.headroom, self.low_ratio)
        rr = RunResult(rung_idx=idx, metrics=m, passed=ok, reasons=reasons, confirm=confirm)
        self.results.append(rr)
        if len(self.results) == 1:
            self.bound = classify_bound(m, self.goal_fps * self.headroom)
            self.margin = max(self.margin_min, m.half_split_diff)
            self.model.bound = self.bound if self.bound in ("gpu", "cpu") else "gpu"
            if self.bound == "cpu":
                self.notes.append(
                    f"CPU bound at the baseline (GPU load {m.median_gpu_load}%): graphics settings cannot lift the average; "
                    f"the search continues on CPU side settings only")
        self.model.observe(self.ladder[idx], 1000.0 / m.avg_fps)
        if confirm:
            self._confirm_pending = None
            self.finished = True
            if not ok:
                self.stepped_down = True
                self.notes.append(f"confirmation run on rung {idx} failed ({'; '.join(reasons)}): stepping down one rung")
        return rr

    def final_rung(self) -> int | None:
        """The rung to leave applied: best passing rung, stepped down when the confirmation failed."""
        b = self.best()
        if b is None:
            return None
        if self.stepped_down:
            conf = [r for r in self.results if r.confirm and not r.passed]
            if conf and conf[-1].rung_idx == b:
                return b - 1 if b > 0 else None
        return b
