"""Fases 2 e 3: transforma as detecções de cada frame em jogadores no mapa.

Para cada frame:
1. detecta cortes de câmera (o tracking recomeça neles) e closes;
2. as pessoas vão para o BoT-SORT (ByteTrack com compensação do movimento da
   câmera), que mantém um ID por jogador;
3. a cor do uniforme de cada ID alimenta o classificador de times;
4. a bola é escolhida entre as candidatas e estimada quando some por pouco tempo;
5. com os pontos-chave do campo, a homografia leva todos para metros no mapa.

Uma "sessão" é uma captura: quando a página começa a capturar de novo, ou o
relógio do navegador volta para trás (página recarregada), tudo recomeça.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .ball import BallTracker
from .patterns import PatternStore
from .insights import InsightEngine
from .stats import MatchStore, StatsTracker, default_data_dir
from .fieldmap import FieldMap
from .pitch import LAST_FIT, CutDetector, HomographyTracker, Keypoints, is_close_up, visible_area
from .teams import OUTLIER, TeamClassifier, jersey_feature

log = logging.getLogger("fc-analytics")

PERSON_LABELS = {"pessoa", "jogador", "goleiro", "árbitro"}
TRACK_ENDED_AFTER_S = 3.0
TRACK_FPS = 7.0
# Tomada aberta: muitos jogadores pequenos na tela (closes e replays ficam de fora da calibração).
WIDE_MIN_PEOPLE = 6
WIDE_MAX_HEIGHT_RATIO = 0.18


@dataclass
class TrackLife:
    first_ts: float
    last_ts: float
    labels: dict[str, int] = field(default_factory=dict)

    def main_label(self) -> str:
        return max(self.labels, key=self.labels.get) if self.labels else "pessoa"


def make_tracker():
    from trackers import BIoU, BoTSORTTracker

    # Ajustado para jogadores pequenos na tela e cerca de 7 frames por segundo:
    # limiares de confiança mais baixos (jogador distante tem confiança baixa),
    # associação mais tolerante e caixas expandidas na comparação (BIoU).
    return BoTSORTTracker(
        lost_track_buffer=int(TRACK_FPS * 2),  # cerca de 2 s para um jogador escondido voltar com o mesmo ID
        frame_rate=TRACK_FPS,
        track_activation_threshold=0.3,
        high_conf_det_threshold=0.35,
        minimum_consecutive_frames=2,
        minimum_iou_threshold_first_assoc=0.15,
        minimum_iou_threshold_second_assoc=0.3,
        minimum_iou_threshold_unconfirmed_assoc=0.2,
        enable_cmc=True,
        iou=BIoU(buffer_ratio=0.3),
    )


def is_wide_shot(people: list[Any], height: int) -> bool:
    if len(people) < WIDE_MIN_PEOPLE:
        return False
    median_h = float(np.median([b.y2 - b.y1 for b in people]))
    return median_h <= WIDE_MAX_HEIGHT_RATIO * height


class Pipeline:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Os padrões dos times sobrevivem a novas capturas; só zeram quando a pessoa pede.
        self.patterns = PatternStore()
        self.patterns_version = 0
        self.patterns_sent = -1
        self.patterns_latest: dict[str, Any] | None = None
        self.patterns_next_ts = 0.0
        self.patterns_busy = False
        # Estatísticas da partida (Fase 4): gravadas no SQLite e retomadas se o backend reiniciar.
        try:
            store = MatchStore.open_default()
        except Exception:  # noqa: BLE001
            log.exception("SQLite indisponível; as estatísticas ficam só na memória")
            store = None
        self.stats = StatsTracker(store)
        # Insights da Fase 5: alertas por regra e análises do LLM local (Ollama).
        self.insights = InsightEngine(store, settings_path=default_data_dir() / "llm.json")
        self.stats_latest: dict[str, Any] | None = None
        self.stats_version = 0
        self.stats_sent = -1
        self.stats_next = 0.0
        self.stats_busy = False
        self.reset()

    def reset(self) -> None:
        self.tracker = make_tracker()
        self.id_offset = 0
        self.max_id = -1
        self.teams = TeamClassifier()
        self.ball = BallTracker()
        self.cuts = CutDetector()
        self.homography = HomographyTracker()
        self.map = FieldMap()
        self.cut_times: deque[float] = deque(maxlen=500)
        self.lives: dict[int, TrackLife] = {}
        self.ended_lifetimes: list[float] = []
        self.track_starts: deque[float] = deque(maxlen=2000)
        self.last_ts: float | None = None

    # ---------- processamento ----------

    def process(
        self, image: np.ndarray, boxes: list[Any], ts: float, keypoints: Keypoints | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if self.last_ts is not None and ts <= self.last_ts:
                self.reset()
            self.last_ts = ts
            start = time.perf_counter()
            out = self._process(image, boxes, ts, keypoints)
            out["trackMs"] = round((time.perf_counter() - start) * 1000, 1)
            return out

    def _on_cut(self, ts: float) -> None:
        """Corte de câmera: os IDs da tomada anterior não valem mais."""
        self.tracker = make_tracker()
        self.id_offset = self.max_id + 1
        self.ball.reset()
        self.homography.reset()
        self.map.forget_ids()
        self.cut_times.append(ts)

    def _process(self, image: np.ndarray, boxes: list[Any], ts: float, keypoints: Keypoints | None) -> dict[str, Any]:
        import supervision as sv

        height, width = image.shape[:2]
        cut = self.cuts.update(image)
        if cut:
            self._on_cut(ts)

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
                gid = int(tid) + self.id_offset if tid >= 0 else -1
                self.max_id = max(self.max_id, gid)
                frame_items.append((gid, box, float(conf), labels_seen[int(cls)]))

        # Times: só os jogadores entram no classificador (o goleiro e o árbitro
        # do modelo de futebol já vêm separados pelo próprio detector).
        wide = is_wide_shot(people, image.shape[0])
        features: list[tuple[int | None, np.ndarray]] = []
        direct_feature: dict[int, np.ndarray] = {}
        for i, (tid, box, _, label) in enumerate(frame_items):
            if tid >= 0:
                life = self.lives.get(tid)
                if life is None:
                    life = self.lives[tid] = TrackLife(first_ts=ts, last_ts=ts)
                    self.track_starts.append(ts)
                life.last_ts = ts
                life.labels[label] = life.labels.get(label, 0) + 1
            if label in ("pessoa", "jogador"):
                feature = jersey_feature(image, box)
                if feature is not None:
                    features.append((tid if tid >= 0 else None, feature))
                    direct_feature[i] = feature
        self.teams.observe_frame(features, ts, wide)

        team_positions: dict[int, list[float]] = {0: [], 1: []}
        resolved: list[tuple[int, tuple[int, int, int, int], float, str, int | None]] = []
        for i, (tid, box, conf, label) in enumerate(frame_items):
            role, team = label, None
            main = self.lives[tid].main_label() if tid >= 0 else label
            if main in ("pessoa", "jogador"):
                if tid >= 0:
                    team_vote = self.teams.team_of(tid)
                elif self.teams.model is not None and i in direct_feature:
                    # Ainda sem ID confirmado: classifica só por este frame.
                    team_vote = self.teams.model.classify(direct_feature[i])
                else:
                    team_vote = None
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

        # Campo: closes e frames sem pontos-chave suficientes pausam o mapa.
        close = is_close_up(people, height)
        view = None if close else self.homography.update(keypoints, width, height, ts)
        if close:
            self.homography.reset()
        if view is not None:
            scene = "ao vivo"
        elif close:
            scene = "close"
        elif keypoints is None:
            scene = "sem modelo do campo"
        else:
            scene = "sem campo"
        self.map.update(view.h if view is not None else None, tracked_boxes, ts, scene)
        snapshot = self.map.snapshot(ts)
        if view is not None and view.fresh:
            self.patterns.observe(snapshot, ts)
            self.stats.observe(snapshot, self.patterns.side.team0_defends_left(), time.time())
        self._maybe_summarize(ts)
        self._maybe_stats()
        field = {
            **snapshot,
            "keypoints": int((keypoints.conf >= 0.5).sum()) if keypoints is not None else 0,
            "fit": dict(LAST_FIT),
            "kp": [
                [round(float(x), 1), round(float(y), 1), i + 1]
                for i, ((x, y), c) in enumerate(zip(keypoints.xy, keypoints.conf))
                if c >= 0.5
            ]
            if keypoints is not None
            else [],
            "cut": cut,
            "view": visible_area(view.h, width, height) if view is not None else None,
            "hInv": [round(float(v), 6) for v in view.h_inv.reshape(-1)] if view is not None else None,
        }

        self._expire(ts)
        counts = {
            "0": sum(1 for b in tracked_boxes if b["t"] == 0),
            "1": sum(1 for b in tracked_boxes if b["t"] == 1),
        }
        patterns = None
        if self.patterns_version != self.patterns_sent:
            patterns, self.patterns_sent = self.patterns_latest, self.patterns_version
        stats = None
        if self.stats_version != self.stats_sent:
            stats, self.stats_sent = self.stats_latest, self.stats_version
        return {
            "stats": stats,
            "boxes": tracked_boxes,
            "map": field,
            "patterns": patterns,
            "wide": wide,
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
            "cutsLastMinute": sum(1 for c in self.cut_times if ts - c <= 60),
            "newLastMinute": recent_new,
            "avgLifeS": round(float(np.mean(lifetimes)), 1) if lifetimes else None,
        }

    # ---------- padrões dos times (calculados em segundo plano a cada 10 s) ----------

    def _maybe_summarize(self, ts: float) -> None:
        if self.patterns_busy or ts < self.patterns_next_ts:
            return
        self.patterns_next_ts = ts + 10.0
        self.patterns_busy = True

        def work() -> None:
            try:
                self.patterns_latest = self.patterns.summary()
                self.patterns_version += 1
            finally:
                self.patterns_busy = False

        threading.Thread(target=work, daemon=True).start()

    def latest_patterns(self) -> dict[str, Any] | None:
        return self.patterns_latest

    def reset_patterns(self) -> None:
        self.patterns.reset()
        self.patterns_latest = self.patterns.summary()
        self.patterns_version += 1

    # ---------- estatísticas da partida (recalculadas em segundo plano a cada 3 s) ----------

    def _maybe_stats(self) -> None:
        now = time.monotonic()
        if self.stats_busy or now < self.stats_next:
            return
        self.stats_next = now + 3.0
        self.stats_busy = True

        def work() -> None:
            try:
                self.refresh_stats()
            except Exception:  # noqa: BLE001
                log.exception("falha ao calcular as estatísticas")
            finally:
                self.stats_busy = False

        threading.Thread(target=work, daemon=True).start()

    def refresh_stats(self) -> dict[str, Any]:
        self.stats_latest = self.stats.summary()
        self.stats_version += 1
        try:
            self.insights.on_stats(self.stats_latest, self.patterns_latest)
        except Exception:  # noqa: BLE001
            log.exception("falha nos insights")
        return self.stats_latest

    def latest_stats(self) -> dict[str, Any]:
        return self.stats_latest if self.stats_latest is not None else self.refresh_stats()

    def new_match(self) -> None:
        """Partida nova: estatísticas, eventos e padrões dos times recomeçam."""
        self.stats.new_match()
        self.reset_patterns()
        self.refresh_stats()

    def recalibrate_teams(self) -> None:
        with self._lock:
            self.teams.recalibrations += 1
            self.teams.reset()
