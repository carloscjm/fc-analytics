"""Acompanhamento da bola.

A bola é pequena e some atrás dos jogadores. Quando há várias candidatas,
fica a mais próxima de onde a bola deveria estar; quando ela some por pouco
tempo, a posição é estimada pela última velocidade e marcada como estimada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAX_MISSING_SECONDS = 0.6
VELOCITY_SMOOTHING = 0.5


@dataclass
class BallState:
    box: tuple[int, int, int, int]
    conf: float
    estimated: bool


class BallTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.center: np.ndarray | None = None
        self.size: np.ndarray | None = None
        self.velocity = np.zeros(2)
        self.seen_ts: float | None = None
        self.conf = 0.0

    def _predict(self, ts: float) -> np.ndarray | None:
        if self.center is None or self.seen_ts is None:
            return None
        return self.center + self.velocity * (ts - self.seen_ts)

    def update(self, candidates: list[tuple[tuple[int, int, int, int], float]], ts: float) -> BallState | None:
        predicted = self._predict(ts)

        if candidates:
            def center_of(box):
                x1, y1, x2, y2 = box
                return np.array([(x1 + x2) / 2, (y1 + y2) / 2])

            if predicted is not None:
                box, conf = min(candidates, key=lambda c: np.linalg.norm(center_of(c[0]) - predicted))
            else:
                box, conf = max(candidates, key=lambda c: c[1])

            new_center = center_of(box)
            if self.center is not None and self.seen_ts is not None and ts > self.seen_ts:
                raw = (new_center - self.center) / (ts - self.seen_ts)
                self.velocity = VELOCITY_SMOOTHING * raw + (1 - VELOCITY_SMOOTHING) * self.velocity
            self.center = new_center
            self.size = np.array([box[2] - box[0], box[3] - box[1]], dtype=float)
            self.seen_ts = ts
            self.conf = conf
            return BallState(box=box, conf=conf, estimated=False)

        if predicted is None or self.seen_ts is None or ts - self.seen_ts > MAX_MISSING_SECONDS:
            return None
        assert self.size is not None
        half = self.size / 2
        x1, y1 = (predicted - half).round().astype(int)
        x2, y2 = (predicted + half).round().astype(int)
        return BallState(box=(int(x1), int(y1), int(x2), int(y2)), conf=self.conf, estimated=True)
