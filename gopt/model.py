"""Multiplicative frametime cost model, calibrated from measured runs.

predicted_frametime(rung) = scale * rel(rung) ** beta
rel(rung) = product over settings of cost[level] / cost[baseline level]
Only GPU side settings count when GPU bound; only CPU flagged ones when CPU bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .adapters import Setting

Rung = dict[str, int]


@dataclass
class CostModel:
    settings: list[Setting]
    baseline: Rung
    bound: str = "gpu"               # gpu | cpu | unknown
    scale: float | None = None       # ms at rel == 1
    beta: float = 1.0
    observations: list[tuple[float, float]] = field(default_factory=list)   # (rel, measured ms)

    def _counts(self, s: Setting) -> bool:
        if self.bound == "cpu":
            return s.cpu
        if self.bound == "gpu":
            return True
        return True

    def rel(self, rung: Rung) -> float:
        r = 1.0
        for s in self.settings:
            if not self._counts(s):
                continue
            lv = rung.get(s.id, self.baseline.get(s.id, 0))
            b = self.baseline.get(s.id, 0)
            r *= s.cost[lv] / s.cost[b]
        return r

    def observe(self, rung: Rung, measured_ms: float):
        self.observations.append((self.rel(rung), measured_ms))
        self._fit()

    def _fit(self):
        obs = [(r, m) for r, m in self.observations if r > 0 and m > 0]
        if not obs:
            return
        if len({round(r, 6) for r, _ in obs}) < 2:
            # one distinct rel: fit the scale only
            self.scale = sum(m / (r ** self.beta) for r, m in obs) / len(obs)
            return
        xs = [math.log(r) for r, _ in obs]
        ys = [math.log(m) for _, m in obs]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        beta = sxy / sxx if sxx else 1.0
        self.beta = min(3.0, max(0.3, beta))
        self.scale = math.exp(my - self.beta * mx)

    def predict_ms(self, rung: Rung) -> float | None:
        if self.scale is None:
            return None
        return self.scale * self.rel(rung) ** self.beta

    def predict_fps(self, rung: Rung) -> float | None:
        ms = self.predict_ms(rung)
        return 1000.0 / ms if ms else None
