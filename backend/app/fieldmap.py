"""Estado do mapa visto de cima: posição de cada jogador e da bola em metros.

- Cada jogador visível é posicionado pelo ponto dos pés (centro de baixo da caixa).
- As posições de cada ID são suavizadas, para o mapa não tremer.
- Quem saiu da imagem continua no mapa, esmaecido, na última posição conhecida,
  por alguns segundos (a câmera da TV não mostra o campo inteiro). Esse "fantasma"
  some se aparecer um ID novo ou um jogador visível ali perto (provavelmente é o
  mesmo jogador com outro ID). IDs que duraram menos de 1 s não viram fantasma.
- Nos closes, replays e frames sem campo, o mapa fica pausado.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from .pitch import LENGTH, WIDTH, apply_h

POSITION_SMOOTHING = 0.6
GHOST_SECONDS = 4.0
GHOST_MIN_LIFE = 1.0
GHOST_MERGE_M = 5.0
NEW_ID_TAKES_GHOST_M = 6.0
GHOSTS_APART_M = 3.0
OUTSIDE_MARGIN_M = 4.0
BALL_TRAIL_SECONDS = 3.0


@dataclass
class MapPlayer:
    x: float
    y: float
    team: int | None
    role: str
    seen_ts: float
    first_ts: float


class FieldMap:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.players: dict[int, MapPlayer] = {}
        self.ball: tuple[float, float, bool] | None = None
        self.ball_ts: float | None = None
        self.trail: deque[tuple[float, float, float]] = deque()
        self.scene = "procurando"
        self.paused_since: float | None = None

    def forget_ids(self) -> None:
        """Num corte de câmera os IDs recomeçam: quem estava no mapa vira fantasma sem ID."""
        self.players = {-(i + 1): p for i, p in enumerate(self.players.values())}

    def update(
        self,
        h: np.ndarray | None,
        boxes: list[dict[str, Any]],
        ts: float,
        scene: str,
    ) -> None:
        self.scene = scene
        if h is None:
            if self.paused_since is None:
                self.paused_since = ts
            return
        self.paused_since = None

        people = [b for b in boxes if b["l"] != "bola" and b.get("id") is not None]
        if people:
            feet = np.array([[(b["b"][0] + b["b"][2]) / 2, b["b"][3]] for b in people], dtype=np.float32)
            meters = apply_h(h, feet)
            for box, (x, y) in zip(people, meters):
                if not self._inside(x, y):
                    continue
                tid = int(box["id"])
                prev = self.players.get(tid)
                if prev is not None:
                    x = POSITION_SMOOTHING * x + (1 - POSITION_SMOOTHING) * prev.x
                    y = POSITION_SMOOTHING * y + (1 - POSITION_SMOOTHING) * prev.y
                    first = prev.first_ts
                else:
                    # ID novo: o fantasma mais próximo provavelmente é o mesmo jogador.
                    self._take_ghost(float(x), float(y), ts)
                    first = ts
                self.players[tid] = MapPlayer(float(x), float(y), box.get("t"), box["l"], ts, first)

        ball = next((b for b in boxes if b["l"] == "bola"), None)
        if ball is not None:
            bx = (ball["b"][0] + ball["b"][2]) / 2
            by = ball["b"][3]
            (x, y), = apply_h(h, np.array([[bx, by]], dtype=np.float32))
            if self._inside(x, y):
                self.ball = (float(x), float(y), bool(ball.get("e")))
                self.ball_ts = ts
                self.trail.append((ts, float(x), float(y)))
        while self.trail and ts - self.trail[0][0] > BALL_TRAIL_SECONDS:
            self.trail.popleft()
        if self.ball_ts is not None and ts - self.ball_ts > 1.0:
            self.ball = None

        for tid in [
            t
            for t, p in self.players.items()
            if ts - p.seen_ts > GHOST_SECONDS
            or (p.seen_ts != ts and p.seen_ts - p.first_ts < GHOST_MIN_LIFE)
        ]:
            del self.players[tid]

    def _take_ghost(self, x: float, y: float, ts: float) -> None:
        best, best_d = None, NEW_ID_TAKES_GHOST_M
        for tid, p in self.players.items():
            if p.seen_ts == ts:
                continue
            d = float(np.hypot(p.x - x, p.y - y))
            if d < best_d:
                best, best_d = tid, d
        if best is not None:
            del self.players[best]

    @staticmethod
    def _inside(x: float, y: float) -> bool:
        m = OUTSIDE_MARGIN_M
        return -m <= x <= LENGTH + m and -m <= y <= WIDTH + m

    def snapshot(self, ts: float) -> dict[str, Any]:
        seen = {tid: p for tid, p in self.players.items() if p.seen_ts == ts}
        ghosts = {tid: p for tid, p in self.players.items() if p.seen_ts != ts}
        out_players = []
        for tid, p in seen.items():
            out_players.append(self._player_json(tid, p, ts, ghost=False))
        kept: list[MapPlayer] = []
        for tid, p in sorted(ghosts.items(), key=lambda item: -item[1].seen_ts):
            # Fantasma redundante: já há um jogador visível (ou um fantasma mais recente) ali.
            if any(np.hypot(q.x - p.x, q.y - p.y) < GHOST_MERGE_M for q in seen.values()):
                continue
            if any(np.hypot(q.x - p.x, q.y - p.y) < GHOSTS_APART_M for q in kept):
                continue
            kept.append(p)
            out_players.append(self._player_json(tid, p, ts, ghost=True))
        return {
            "scene": self.scene,
            "pausedS": round(ts - self.paused_since, 1) if self.paused_since is not None else 0,
            "players": out_players,
            "ball": {"x": round(self.ball[0], 2), "y": round(self.ball[1], 2), "e": self.ball[2]} if self.ball else None,
            "trail": [[round(x, 2), round(y, 2)] for _, x, y in self.trail],
        }

    @staticmethod
    def _player_json(tid: int, p: MapPlayer, ts: float, ghost: bool) -> dict[str, Any]:
        return {
            "id": tid if tid >= 0 else None,
            "x": round(p.x, 2),
            "y": round(p.y, 2),
            "t": p.team,
            "l": p.role,
            "g": ghost,
            "age": round(ts - p.seen_ts, 1),
        }
