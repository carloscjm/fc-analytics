"""Separação dos times pela cor do uniforme.

Para cada jogador rastreado, pega a cor do tronco (sem o verde do gramado) e,
depois de alguns segundos de jogo, agrupa as cores em dois times com k-means.
Quem fica longe das duas cores (árbitro, goleiros, comissão técnica) é
marcado como "fora do padrão". Cada ID vota a cada frame e vale a maioria,
para um frame ruim não trocar o time de ninguém.
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

CALIBRATION_SECONDS = 30.0
ENOUGH_TRACKS = 14
MIN_TRACKS = 6
MIN_SAMPLES_PER_TRACK = 3
OUTLIER_RATIO = 2.5
OUTLIER_MIN_DISTANCE = 18.0
VOTES_KEPT = 12

OUTLIER = 2


def jersey_feature(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    """Cor mediana do tronco do jogador, em Lab, sem os pixels de gramado."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w < 6 or h < 12:
        return None
    H, W = image.shape[:2]
    cx1, cx2 = max(0, x1 + int(w * 0.25)), min(W, x2 - int(w * 0.25))
    cy1, cy2 = max(0, y1 + int(h * 0.15)), min(H, y1 + int(h * 0.5))
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    crop = image[cy1:cy2, cx1:cx2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    keep = cv2.inRange(hsv, GRASS_LOW, GRASS_HIGH).reshape(-1) == 0
    if keep.sum() < 12:
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


class TeamClassifier:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.model: TeamModel | None = None
        self.samples: dict[int, list[np.ndarray]] = defaultdict(list)
        self.votes: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=VOTES_KEPT))
        self.start_ts: float | None = None
        self.last_ts: float = 0.0

    @property
    def ready(self) -> bool:
        return self.model is not None

    def _calibration_tracks(self) -> list[int]:
        return [tid for tid, s in self.samples.items() if len(s) >= MIN_SAMPLES_PER_TRACK]

    def progress(self) -> float:
        if self.ready:
            return 1.0
        if self.start_ts is None:
            return 0.0
        by_time = (self.last_ts - self.start_ts) / CALIBRATION_SECONDS
        by_tracks = len(self._calibration_tracks()) / ENOUGH_TRACKS
        return float(min(1.0, max(by_time, by_tracks)))

    def observe(self, track_id: int, feature: np.ndarray, ts: float) -> None:
        if self.start_ts is None:
            self.start_ts = ts
        self.last_ts = ts
        if self.model is None:
            if len(self.samples[track_id]) < 20:
                self.samples[track_id].append(feature)
            self._maybe_fit()
        else:
            self.votes[track_id].append(self.model.classify(feature))

    def _maybe_fit(self) -> None:
        tracks = self._calibration_tracks()
        elapsed = self.last_ts - (self.start_ts or self.last_ts)
        if len(tracks) >= ENOUGH_TRACKS or (elapsed >= CALIBRATION_SECONDS and len(tracks) >= MIN_TRACKS):
            self.fit()

    def fit(self) -> bool:
        tracks = self._calibration_tracks()
        if len(tracks) < MIN_TRACKS:
            return False
        means = np.array([np.median(self.samples[t], axis=0) for t in tracks], dtype=np.float32)

        centers, labels = kmeans(means)
        dist = np.linalg.norm(means - centers[labels], axis=1)
        spreads = np.array([np.median(dist[labels == j]) if np.any(labels == j) else 0.0 for j in range(2)])
        limit = np.maximum(OUTLIER_RATIO * spreads[labels], OUTLIER_MIN_DISTANCE)
        inliers = dist <= limit
        if inliers.sum() >= MIN_TRACKS:
            centers, labels_in = kmeans(means[inliers])
            dist_in = np.linalg.norm(means[inliers] - centers[labels_in], axis=1)
            spreads = np.array(
                [np.median(dist_in[labels_in == j]) if np.any(labels_in == j) else 0.0 for j in range(2)]
            )

        # Ordem estável: o time 0 é o de camisa mais clara.
        order = np.argsort(-centers[:, 0])
        self.model = TeamModel(centers=centers[order], spreads=np.maximum(spreads[order], 4.0))

        for tid, feats in self.samples.items():
            for f in feats[-VOTES_KEPT:]:
                self.votes[tid].append(self.model.classify(f))
        self.samples.clear()
        return True

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
        }
