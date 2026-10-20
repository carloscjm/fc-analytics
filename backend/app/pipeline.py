"""Fase 2: transforma as detecções de cada frame em jogadores rastreados.

Para cada frame:
1. as pessoas vão para o BoT-SORT (ByteTrack com compensação do movimento da
   câmera), que mantém um ID por jogador;
2. a cor do uniforme de cada ID alimenta o classificador de times;
3. a bola é escolhida entre as candidatas e estimada quando some por pouco tempo.

Uma "sessão" é uma captura: quando a página começa a capturar de novo, ou o
relógio do navegador volta para trás (página recarregada), tudo recomeça.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .ball import BallTracker
from .teams import OUTLIER, TeamClassifier, jersey_feature

PERSON_LABELS = {"pessoa", "jogador", "goleiro", "árbitro"}
TRACK_ENDED_AFTER_S = 3.0
TRACK_FPS = 7.0


@dataclass
class TrackLife:
    first_ts: float
    last_ts: float
    labels: dict[str, int] = field(default_factory=dict)

    def main_label(self) -> str:
        return max(self.labels, key=self.labels.get) if self.labels else "pessoa"


def make_tracker():
    from trackers import BoTSORTTracker

    return BoTSORTTracker(
        lost_track_buffer=int(TRACK_FPS * 2),  # cerca de 2 s para um jogador escondido voltar com o mesmo ID
        frame_rate=TRACK_FPS,
        track_activation_threshold=0.4,
        high_conf_det_threshold=0.5,
        minimum_consecutive_frames=2,
        enable_cmc=True,
    )


class Pipeline:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.tracker = make_tracker()
        self.teams = TeamClassifier()
        self.ball = BallTracker()
        self.lives: dict[int, TrackLife] = {}
        self.ended_lifetimes: list[float] = []
        self.track_starts: deque[float] = deque(maxlen=2000)
        self.last_ts: float | None = None

    # ---------- processamento ----------

    def process(self, image: np.ndarray, boxes: list[Any], ts: float) -> dict[str, Any]:
        with self._lock:
            if self.last_ts is not None and ts <= self.last_ts:
                self.reset()
            self.last_ts = ts
            start = time.perf_counter()
            out = self._process(image, boxes, ts)
            out["trackMs"] = round((time.perf_counter() - start) * 1000, 1)
            return out

    def _process(self, image: np.ndarray, boxes: list[Any], ts: float) -> dict[str, Any]:
        import supervision as sv

        people = [b for b in boxes if b.label in PERSON_LABELS]
        balls = [b for b in boxes if b.label == "bola"]
        labels_seen = sorted({b.label for b in people})
        label_index = {label: i for i, label in enumerate(labels_seen)}

        tracked_boxes: list[dict[str, Any]] = []
        if people:
            detections = sv.Detections(
                xyxy=np.array([[b.x1, b.y1, b.x2, b.y2] for b in people], dtype=float),
                confidence=np.array([b.conf for b in people], dtype=float),
                class_id=np.array([label_index[b.label] for b in people], dtype=int),
            )
            tracked = self.tracker.update(detections, frame=image, timestamp=ts)
        else:
            tracked = None

        frame_items: list[tuple[int, tuple[int, int, int, int], float, str]] = []
        if tracked is not None:
            for xyxy, conf, cls, tid in zip(tracked.xyxy, tracked.confidence, tracked.class_id, tracked.tracker_id):
                box = tuple(int(v) for v in np.round(xyxy))
                frame_items.append((int(tid), box, float(conf), labels_seen[int(cls)]))

        # Times: só os jogadores entram no classificador (o goleiro e o árbitro
        # do modelo de futebol já vêm separados pelo próprio detector).
        for tid, box, _, label in frame_items:
            if tid < 0:
                continue
            life = self.lives.get(tid)
            if life is None:
                life = self.lives[tid] = TrackLife(first_ts=ts, last_ts=ts)
                self.track_starts.append(ts)
            life.last_ts = ts
            life.labels[label] = life.labels.get(label, 0) + 1
            if label in ("pessoa", "jogador"):
                feature = jersey_feature(image, box)
                if feature is not None:
                    self.teams.observe(tid, feature, ts)

        team_positions: dict[int, list[float]] = {0: [], 1: []}
        resolved: list[tuple[int, tuple[int, int, int, int], float, str, int | None]] = []
        for tid, box, conf, label in frame_items:
            role, team = label, None
            if tid >= 0:
                main = self.lives[tid].main_label()
                if main in ("pessoa", "jogador"):
                    team_vote = self.teams.team_of(tid)
                    if team_vote == OUTLIER:
                        role = "árbitro/goleiro"
                    elif team_vote is not None:
                        role, team = "jogador", team_vote
                        team_positions[team].append((box[0] + box[2]) / 2)
                else:
                    role = main
            resolved.append((tid, box, conf, role, team))

        for tid, box, conf, role, team in resolved:
            if role == "goleiro" and team_positions[0] and team_positions[1]:
                cx = (box[0] + box[2]) / 2
                d0 = abs(np.mean(team_positions[0]) - cx)
                d1 = abs(np.mean(team_positions[1]) - cx)
                team = 0 if d0 < d1 else 1
            tracked_boxes.append(
                {"b": list(box), "c": round(conf, 3), "l": role, "id": tid if tid >= 0 else None, "t": team}
            )

        ball = self.ball.update([((b.x1, b.y1, b.x2, b.y2), b.conf) for b in balls], ts)
        if ball is not None:
            tracked_boxes.append(
                {"b": list(ball.box), "c": round(ball.conf, 3), "l": "bola", "id": None, "t": None, "e": ball.estimated}
            )

        self._expire(ts)
        counts = {
            "0": sum(1 for b in tracked_boxes if b["t"] == 0),
            "1": sum(1 for b in tracked_boxes if b["t"] == 1),
        }
        return {
            "boxes": tracked_boxes,
            "teams": {**self.teams.info(), "counts": counts},
            "tracking": self._stats(ts, active=sum(1 for b in tracked_boxes if b["id"] is not None)),
        }

    # ---------- métricas de estabilidade dos IDs ----------

    def _expire(self, ts: float) -> None:
        for tid in [t for t, life in self.lives.items() if ts - life.last_ts > TRACK_ENDED_AFTER_S]:
            life = self.lives.pop(tid)
            self.ended_lifetimes.append(life.last_ts - life.first_ts)
            if len(self.ended_lifetimes) > 500:
                self.ended_lifetimes = self.ended_lifetimes[-500:]

    def _stats(self, ts: float, active: int) -> dict[str, Any]:
        recent_new = sum(1 for start in self.track_starts if ts - start <= 60)
        lifetimes = self.ended_lifetimes[-100:] + [ts - life.first_ts for life in self.lives.values()]
        return {
            "active": active,
            "newLastMinute": recent_new,
            "avgLifeS": round(float(np.mean(lifetimes)), 1) if lifetimes else None,
        }

    def recalibrate_teams(self) -> None:
        with self._lock:
            self.teams.reset()
