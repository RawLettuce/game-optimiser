import random

import pytest

from gopt.adapters import Adapter
from gopt.metrics import Metrics
from gopt.model import CostModel
from gopt.search import build_ladder, describe_rung, nearest_rung, Search


def fake_metrics(avg, low_ratio=0.85, spikes_per_min=0.0, gpu_load=95.0, cpu_load=40.0, split=0.02):
    return Metrics(frames=3000, duration_s=50.0, avg_fps=round(avg, 1), low1_avg_fps=round(avg * low_ratio, 1),
                   low1_integral_fps=round(avg * low_ratio, 1), low01_avg_fps=round(avg * 0.6, 1), p1_fps=round(avg * low_ratio, 1),
                   median_frametime_ms=round(1000 / avg, 3), max_frametime_ms=40.0, spikes=int(spikes_per_min),
                   spikes_per_min=spikes_per_min, median_gpu_load=gpu_load, median_cpu_load=cpu_load,
                   max_vram_mb=5000.0, half_split_diff=split)


def test_ladder_is_monotone_and_complete():
    ad = Adapter.load("warframe")
    ladder = build_ladder(ad.settings)
    assert all(v == 0 for v in ladder[0].values())
    assert all(ladder[-1][s.id] == s.top for s in ad.settings)
    assert len(ladder) == 1 + sum(s.top for s in ad.settings)
    for a, b in zip(ladder, ladder[1:]):
        diff = [(k, a[k], b[k]) for k in a if a[k] != b[k]]
        assert len(diff) == 1 and diff[0][2] == diff[0][1] + 1
    # predicted frametime never decreases along the ladder
    m = CostModel(ad.settings, ladder[0])
    rels = [m.rel(r) for r in ladder]
    assert all(b >= a for a, b in zip(rels, rels[1:]))
    # cheap high value settings first: anti aliasing and textures before Ludicrous shadows
    idx_of = lambda sid, lv: next(i for i, r in enumerate(ladder) if r[sid] == lv)
    assert idx_of("textures", 2) < idx_of("shadows", 3)
    assert "Shadow Quality=Low" in describe_rung(ad, ladder[0])


def test_ladder_pins_and_no_upscaling_and_vram_cap():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings, pins={"shadows": 2}, no_upscaling=True, vram_cap_mb=7500)
    assert all(r["shadows"] == 2 for r in ladder)
    assert all(r["fsr"] == ad.setting("fsr").top for r in ladder)      # FSR off everywhere
    assert max(r["textures"] for r in ladder) == 1                      # High needs 8900 MB > cap
    ladder2 = build_ladder(ad.settings)
    assert ladder2[0]["fsr"] == 0 and ladder2[-1]["textures"] == 2


def test_nearest_rung():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    assert nearest_rung(ladder, {s.id: s.top for s in ad.settings}) == len(ladder) - 1
    assert nearest_rung(ladder, {s.id: 0 for s in ad.settings}) == 0
    assert nearest_rung(ladder, {"shadows": None, "msaa": None}) == 0


def test_cost_model_fits_scale_then_slope():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    m = CostModel(ad.settings, ladder[10])
    assert m.predict_fps(ladder[10]) is None
    m.observe(ladder[10], 5.0)
    assert m.predict_ms(ladder[10]) == pytest.approx(5.0)
    assert m.predict_ms(ladder[-1]) > 5.0 > m.predict_ms(ladder[0])
    # a second observation with the true slope twice the table's: beta should rise
    true_ms = 5.0 * m.rel(ladder[-1]) ** 2.0
    m.observe(ladder[-1], true_ms)
    assert 1.5 < m.beta <= 3.0
    assert m.predict_ms(ladder[-1]) == pytest.approx(true_ms, rel=0.05)


def test_cpu_bound_model_only_counts_cpu_settings():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    m = CostModel(ad.settings, ladder[0], bound="cpu")
    top = dict(ladder[-1])
    only_gpu = dict(ladder[0], msaa=3, fsr=4)
    assert m.rel(only_gpu) == pytest.approx(1.0)
    assert m.rel(top) > 1.0


class Truth:
    """Synthetic game: fps = base / rel_true(rung) ** gamma with noise; counts runs."""

    def __init__(self, settings, ladder, base_fps, gamma, noise, seed):
        self.model = CostModel(settings, ladder[0])
        self.base, self.gamma, self.noise = base_fps, gamma, noise
        self.rnd = random.Random(seed)
        self.ladder = ladder
        self.runs = 0

    def true_fps(self, idx):
        return self.base / self.model.rel(self.ladder[idx]) ** self.gamma

    def measure(self, idx):
        self.runs += 1
        f = self.true_fps(idx) * (1 + self.rnd.gauss(0, self.noise))
        return fake_metrics(f)


def run_search(ad, ladder, truth, goal, start, max_runs=6):
    s = Search(ad, ladder, goal, start_idx=start, max_runs=max_runs, headroom=1.0)
    while (idx := s.next_rung()) is not None:
        s.record(idx, truth.measure(idx))
    return s


@pytest.mark.parametrize("game", ["warframe", "cs2"])
def test_search_meets_goal_within_budget_and_never_lies(game):
    ad = Adapter.load(game)
    ladder = build_ladder(ad.settings)
    rnd = random.Random(42)
    budgets, found, unreachable = [], 0, 0
    for trial in range(50):
        gamma = rnd.uniform(0.6, 1.6)
        base = rnd.uniform(60, 400)
        truth = Truth(ad.settings, ladder, base, gamma, noise=0.02, seed=trial)
        lo, hi = truth.true_fps(len(ladder) - 1), truth.true_fps(0)
        goal = rnd.uniform(lo * 0.8, hi * 1.1)
        start = rnd.randrange(len(ladder))
        s = run_search(ad, ladder, truth, goal, start)
        budgets.append(truth.runs)
        assert truth.runs <= 6
        fr = s.final_rung()
        # never report a rung that was not measured as passing (or one below it)
        if fr is not None:
            measured_pass = [r.rung_idx for r in s.results if r.passed]
            assert fr in measured_pass or (fr + 1 in measured_pass and s.stepped_down)
            found += 1
        else:
            unreachable += 1
            # when nothing passed, the goal is genuinely hard: the lowest rung is within noise of the goal or below it
            assert hi < goal * 1.1, (goal, hi)
    assert found >= 30
    print(f"\n{game}: mean runs {sum(budgets)/len(budgets):.2f}, found {found}, unreachable {unreachable}, ladder {len(ladder)}")
    assert sum(budgets) / len(budgets) <= 5.0


def test_search_top_rung_passes_immediately():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 100.0, start_idx=len(ladder) - 1, headroom=1.0)
    idx = s.next_rung()
    assert idx == len(ladder) - 1
    s.record(idx, fake_metrics(104, split=0.03))
    # a narrow pass gets one confirmation run, then done
    assert s.next_rung() == idx
    s.record(idx, fake_metrics(104, split=0.03))
    assert s.next_rung() is None and s.final_rung() == idx
    # a comfortable pass at the top needs no second run
    s2 = Search(ad, ladder, 100.0, start_idx=len(ladder) - 1, headroom=1.0)
    s2.record(s2.next_rung(), fake_metrics(300))
    assert s2.next_rung() is None and s2.final_rung() == len(ladder) - 1


def test_search_bottom_rung_fails_reports_best_none():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 500.0, start_idx=0, headroom=1.0)
    s.record(s.next_rung(), fake_metrics(200))
    assert s.next_rung() is None
    assert s.final_rung() is None
    assert any("not reachable" in n for n in s.notes)


def test_confirmation_failure_steps_down():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 100.0, start_idx=5, headroom=1.0)
    s.record(s.next_rung(), fake_metrics(104, split=0.03))   # rung 5 passes, but not comfortably
    idx = s.next_rung()
    assert idx > 5
    nxt = idx
    while nxt is not None and not s._confirm_pending:
        s.record(nxt, fake_metrics(90))                 # everything above 5 fails
        nxt = s.next_rung()
    # now a confirmation on the best passing rung (5)
    assert s._confirm_pending == 5 and nxt == 5
    s.record(5, fake_metrics(95))                       # confirmation fails
    assert s.stepped_down and s.final_rung() == 4


def test_comfortable_pass_skips_confirmation():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 100.0, start_idx=5, headroom=1.0)
    s.record(s.next_rung(), fake_metrics(150))
    idx = s.next_rung()
    assert idx > 5
    s.record(idx, fake_metrics(80))
    nxt = s.next_rung()
    while nxt is not None:
        s.record(nxt, fake_metrics(80 if nxt > 5 else 150))
        nxt = s.next_rung()
    assert s.final_rung() >= 5
    assert not any(r.confirm for r in s.results)


def test_cpu_bound_note_and_margin_from_noise():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 240.0, start_idx=10, headroom=1.0)
    s.record(s.next_rung(), fake_metrics(190, gpu_load=55, cpu_load=92, split=0.08))
    assert s.bound == "cpu" and s.margin == 0.08
    assert any("CPU bound" in n for n in s.notes)


def test_inversion_prefers_lower_rung():
    ad = Adapter.load("cs2")
    ladder = build_ladder(ad.settings)
    s = Search(ad, ladder, 100.0, start_idx=3, headroom=1.0, max_runs=10)
    s.results.clear()
    from gopt.search import RunResult
    s.results.append(RunResult(3, fake_metrics(120), True, []))
    s.results.append(RunResult(8, fake_metrics(90), False, ["average"]))
    s.results.append(RunResult(12, fake_metrics(130), True, []))
    assert s.inversions()
    assert s.best() == 3
    assert s.next_rung() is None


def test_phases_native_first_then_fallback_only():
    from gopt.search import build_phases
    ad = Adapter.load("warframe")
    ups = ad.setting("upscaling")
    phases = build_phases(ad.settings)
    assert [p["name"] for p in phases] == ["native", "DLSS Quality"]
    assert {r["upscaling"] for r in phases[0]["ladder"]} == {ups.top}
    assert {r["upscaling"] for r in phases[1]["ladder"]} == {ups.levels.index("DLSS_QUALITY")}
    assert len(build_phases(ad.settings, no_upscaling=True)) == 1
    pinned = build_phases(ad.settings, pins={"upscaling": 0})
    assert len(pinned) == 1 and {r["upscaling"] for r in pinned[0]["ladder"]} == {0}


def test_unreachable_goal_measures_the_bottom_rung_second():
    ad = Adapter.load("warframe")
    from gopt.search import build_phases
    ladder = build_phases(ad.settings)[0]["ladder"]
    s = Search(ad, ladder, goal_fps=500.0, start_idx=len(ladder) - 2, max_runs=6)
    first = s.next_rung()
    s.record(first, fake_metrics(60.0))
    assert s.next_rung() == 0
