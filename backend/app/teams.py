"""Separação dos times pela cor do uniforme.

Para cada jogador, pega a cor do tronco (sem o verde do gramado). A calibração
usa só as tomadas abertas, onde aparecem muitos jogadores dos dois times; closes
e replays mostram poucos jogadores e muita gente de fora (comissão, torcida) e
distorciam as cores.

Na calibração, as cores de todas as detecções das tomadas abertas são agrupadas
em 4 grupos; os dois maiores, com cores bem diferentes, viram os times. Os
grupos pequenos costumam ser árbitro, goleiros e comissão técnica. Depois,
quem fica longe das duas cores dos times é marcado como "fora do padrão".

Cada ID vota a cada frame e vale a maioria, para um frame ruim não trocar o
time de ninguém. Se a calibração estiver ruim (muita gente fora do padrão ou um
time quase sumindo nas tomadas abertas), ela é refeita sozinha.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

# Faixa de verde do gramado em HSV do OpenCV (matiz de 0 a 180).
GRASS_LOW = np.array([30, 40, 40], dtype=np.uint8)
GRASS_HIGH = np.array([90, 255, 255], dtype=np.uint8)
# O brilho (L) varia com sombra e iluminação; pesa menos que a cor (a, b).
L_WEIGHT = 0.5

# Calibração
MIN_WIDE_FRAMES = 8
MIN_POOL = 80
CALIBRATION_SECONDS = 30.0
MIN_POOL_AFTER_TIMEOUT = 40
POOL_LIMIT = 3000
CLUSTERS = 4
MIN_TEAM_DISTANCE = 15.0

# Classificação
OUTLIER_RATIO = 2.5
OUTLIER_MIN_DISTANCE = 18.0
VOTES_KEPT = 12

# Autocorreção
HEALTH_WINDOW = 300
HEALTH_MIN_SAMPLES = 200
MAX_OUTLIER_SHARE = 0.45
MIN_TEAM_SHARE = 0.12

OUTLIER = 2


def jersey_feature(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    """Cor mediana do tronco do jogador, em Lab, sem os pixels de gramado."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w < 5 or h < 10:
        return None
    H, W = image.shape[:2]
    cx1, cx2 = max(0, x1 + int(w * 0.25)), min(W, x2 - int(w * 0.25))
    cy1, cy2 = max(0, y1 + int(h * 0.15)), min(H, y1 + int(h * 0.5))
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    crop = image[cy1:cy2, cx1:cx2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    keep = cv2.inRange(hsv, GRASS_LOW, GRASS_HIGH).reshape(-1) == 0
    if keep.sum() < 6:
        return None
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).reshape(-1, 3)[keep].astype(np.float32)
    feature = np.median(lab, axis=0)
    feature[0] *= L_WEIGHT
    return feature


def kmeans(points: np.ndarray, k: int = 2, iters: int = 30, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """k-means simples com inicialização k-means++ (determinística pela semente)."""
    rng = np.random.default_rng(seed)
    centroids = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        d2 = np.min([np.sum((points - c) ** 2, axis=1) for c in centroids], axis=0)
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(len(points), 1 / len(points))
        centroids.append(points[rng.choice(len(points), p=probs)])
    centers = np.array(centroids, dtype=np.float32)
    labels = np.zeros(len(points), dtype=int)
    for _ in range(iters):
        dist = np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=2)
        labels = dist.argmin(axis=1)
        new = np.array([points[labels == j].mean(axis=0) if np.any(labels == j) else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new.astype(np.float32)
    return centers, labels


def lab_to_hex(feature: np.ndarray) -> str:
    lab = feature.copy()
    lab[0] /= L_WEIGHT
    pixel = np.clip(lab, 0, 255).astype(np.uint8).reshape(1, 1, 3)
    b, g, r = cv2.cvtColor(pixel, cv2.COLOR_LAB2BGR)[0, 0]
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass
class TeamModel:
    centers: np.ndarray  # (2, 3)
    spreads: np.ndarray  # distância típica de um jogador ao centro do seu time

    def classify(self, feature: np.ndarray) -> int:
        dist = np.linalg.norm(self.centers - feature, axis=1)
        team = int(dist.argmin())
        limit = max(OUTLIER_RATIO * float(self.spreads[team]), OUTLIER_MIN_DISTANCE)
        return OUTLIER if dist[team] > limit else team


def fit_teams(pool: np.ndarray, clusters: int = CLUSTERS) -> TeamModel | None:
    """Os dois maiores grupos de cor, desde que bem diferentes entre si, viram os times."""
    k = min(clusters, max(2, len(pool) // 10))
    best: tuple[float, TeamModel] | None = None
    for seed in range(3):
        centers, labels = kmeans(pool, k=k, seed=seed)
        sizes = np.bincount(labels, minlength=k)
        order = list(np.argsort(-sizes))
        first = order[0]
        second = next(
            (j for j in order[1:] if np.linalg.norm(centers[j] - centers[first]) >= MIN_TEAM_DISTANCE), None
        )
        if second is None:
            continue
        chosen = [first, second]
        spreads = []
        for j in chosen:
            members = pool[labels == j]
            spreads.append(float(np.median(np.linalg.norm(members - centers[j], axis=1))))
        coverage = float(sizes[chosen].sum()) / len(pool)
        model = TeamModel(centers=centers[chosen].astype(np.float32), spreads=np.maximum(np.array(spreads), 4.0))
        if best is None or coverage > best[0]:
            best = (coverage, model)
    if best is None:
        return None
    model = best[1]
    # Ordem estável: o time A é o de camisa mais clara.
    order = np.argsort(-model.centers[:, 0])
    return TeamModel(centers=model.centers[order], spreads=model.spreads[order])


class TeamClassifier:
    def __init__(self) -> None:
        self.recalibrations = 0
        self.reset()

    def reset(self) -> None:
        self.model: TeamModel | None = None
        self.pool: list[np.ndarray] = []
        self.wide_frames = 0
        self.votes: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=VOTES_KEPT))
        self.health: deque[int] = deque(maxlen=HEALTH_WINDOW)
        self.start_ts: float | None = None
        self.last_ts: float = 0.0

    @property
    def ready(self) -> bool:
        return self.model is not None

    def progress(self) -> float:
        if self.ready:
            return 1.0
        by_frames = self.wide_frames / MIN_WIDE_FRAMES
        by_pool = len(self.pool) / MIN_POOL
        return float(min(0.99, min(by_frames, by_pool)))

    def observe_frame(self, features: list[tuple[int | None, np.ndarray]], ts: float, wide: bool) -> None:
        """Recebe as cores de todos os jogadores de um frame (com o ID, quando houver)."""
        if self.start_ts is None:
            self.start_ts = ts
        self.last_ts = ts

        if self.model is None:
            if wide and features:
                self.wide_frames += 1
                self.pool.extend(f for _, f in features)
                if len(self.pool) > POOL_LIMIT:
                    self.pool = self.pool[-POOL_LIMIT:]
            self._maybe_fit()
            return

        for tid, feature in features:
            team = self.model.classify(feature)
            if tid is not None:
                self.votes[tid].append(team)
            if wide:
                self.health.append(team)
        if wide:
            self._check_health()

    def _maybe_fit(self) -> None:
        elapsed = self.last_ts - (self.start_ts or self.last_ts)
        enough = self.wide_frames >= MIN_WIDE_FRAMES and len(self.pool) >= MIN_POOL
        timeout = elapsed >= CALIBRATION_SECONDS and len(self.pool) >= MIN_POOL_AFTER_TIMEOUT
        if enough or timeout:
            self.fit()

    def fit(self) -> bool:
        if len(self.pool) < 20:
            return False
        model = fit_teams(np.array(self.pool, dtype=np.float32))
        if model is None:
            return False
        self.model = model
        self.pool = []
        return True

    def _check_health(self) -> None:
        if len(self.health) < HEALTH_MIN_SAMPLES:
            return
        values = np.array(self.health)
        outliers = float(np.mean(values == OUTLIER))
        team_a = float(np.mean(values == 0))
        team_b = float(np.mean(values == 1))
        if outliers > MAX_OUTLIER_SHARE or min(team_a, team_b) < MIN_TEAM_SHARE:
            self.recalibrations += 1
            self.reset()

    def team_of(self, track_id: int) -> int | None:
        """0 ou 1 para os times, OUTLIER para fora do padrão, None se ainda não sabe."""
        votes = self.votes.get(track_id)
        if not self.ready or not votes:
            return None
        values, counts = np.unique(np.array(votes), return_counts=True)
        return int(values[counts.argmax()])

    def info(self) -> dict[str, Any]:
        return {
            "state": "pronto" if self.ready else "calibrando",
            "progress": round(self.progress(), 2),
            "colors": [lab_to_hex(c) for c in self.model.centers] if self.model else None,
            "recalibrations": self.recalibrations,
        }
