"""Padrões de cada time: como ataca e como defende.

Em vez de mostrar o jogo ao vivo, o mapa resume o comportamento de cada time:

1. **Fase do jogo.** Em cada frame, decide quem está com a bola: o time do
   jogador mais perto da bola (no campo, em metros). Sem bola visível, vale o
   time que está mais avançado no campo. Quem tem a bola ataca; o outro defende.
2. **Lado de cada time.** Para comparar o jogo todo (os times trocam de lado no
   intervalo), as posições são giradas para cada time atacar sempre da
   esquerda para a direita. O lado de cada time vem do goleiro e de onde o time
   fica quando defende, com memória de alguns minutos.
3. **Padrão.** As posições de cada time em cada fase vão se acumulando. A cada
   alguns segundos, o backend agrupa essas posições em 10 posições médias
   (os jogadores de linha), organiza em linhas (defesa, meio, ataque) e calcula
   a formação, a altura da linha de defesa, a largura, a profundidade, o
   corredor preferido no ataque e um mapa de calor.

Limite importante: a câmera da TV não mostra o campo inteiro, então as médias
são feitas com quem aparece (e quem saiu da imagem há pouco). O padrão é uma
aproximação que melhora com mais minutos de jogo.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .pitch import LENGTH, WIDTH
from .teams import kmeans

PHASES = ("ataque", "defesa")
POSSESSION_RADIUS_M = 4.0
POSSESSION_CONFIRM_FRAMES = 2
POSSESSION_MEMORY_S = 3.0
TILT_MIN_DIFF_M = 6.0
MIN_PLAYERS_PER_FRAME = 5
GHOST_MAX_AGE_S = 2.0
MAX_FRAMES = 4000
MIN_FRAMES_FOR_PATTERN = 40
ROLES = 10
SIDE_HALF_LIFE_S = 120.0
HEAT_CELL_M = 5.0
LINE_GAP_SPLIT_M = 5.0

OUTFIELD_ROLES = {"jogador", "pessoa"}


@dataclass
class SideEstimator:
    """Positivo = o time 0 defende o gol da esquerda (x = 0)."""

    score: float = 0.0
    last_ts: float | None = None

    def add(self, evidence: float, ts: float) -> None:
        if self.last_ts is not None and ts > self.last_ts:
            self.score *= 0.5 ** ((ts - self.last_ts) / SIDE_HALF_LIFE_S)
        self.last_ts = ts
        self.score += evidence

    def team0_defends_left(self) -> bool | None:
        if abs(self.score) < 1.0:
            return None
        return self.score > 0


@dataclass
class PhaseSamples:
    frames: deque = field(default_factory=lambda: deque(maxlen=MAX_FRAMES))
    seconds: float = 0.0


def normalize(points: np.ndarray, defends_left: bool) -> np.ndarray:
    """Gira o campo para o time atacar da esquerda para a direita (a esquerda do time fica em y pequeno)."""
    if defends_left:
        return points
    return np.column_stack([LENGTH - points[:, 0], WIDTH - points[:, 1]])


def split_lines(xs: np.ndarray) -> list[list[int]]:
    """Divide as 10 posições (pela profundidade) em 3 ou 4 linhas, de trás para a frente.

    Testa todas as divisões possíveis e fica com a de linhas mais "retas" (menor
    variação de profundidade dentro de cada linha), respeitando o que existe no
    futebol: defesa com 3 a 5 jogadores e ataque com 1 a 3. Uma quarta linha só
    entra se separar bem melhor do que três.
    """
    from itertools import combinations

    order = np.argsort(xs)
    sorted_x = xs[order]
    n = len(sorted_x)
    best: tuple[float, list[list[int]]] | None = None
    for k in (3, 4):
        for cuts in combinations(range(1, n), k - 1):
            bounds = (0, *cuts, n)
            sizes = [bounds[i + 1] - bounds[i] for i in range(k)]
            if not (3 <= sizes[0] <= 5 and 1 <= sizes[-1] <= 3):
                continue
            cost = sum(float(np.var(sorted_x[bounds[i] : bounds[i + 1]])) * sizes[i] for i in range(k))
            if k == 4:
                cost += LINE_GAP_SPLIT_M**2 * 1.5
            if best is None or cost < best[0]:
                groups = [list(order[bounds[i] : bounds[i + 1]]) for i in range(k)]
                best = (cost, groups)
    if best is None:
        return [list(order)]
    return best[1]


def describe_block(line_height: float) -> str:
    if line_height < 30:
        return "baixo"
    if line_height < 42:
        return "médio"
    return "alto"


def best_roles(points: np.ndarray, restarts: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """k-means com vários recomeços: fica o agrupamento mais compacto.

    Um único k-means às vezes junta dois jogadores numa posição e divide outro
    em duas; o mais compacto entre vários recomeços quase sempre acerta.
    Penaliza posições com quase nenhum dado (metade de um jogador dividido).
    """
    sample = points
    if len(points) > 6000:
        sample = points[np.random.default_rng(0).choice(len(points), 6000, replace=False)]
    best = None
    for seed in range(restarts):
        centers, labels = kmeans(sample, k=ROLES, iters=40, seed=seed)
        inertia = float(np.sum((sample - centers[labels]) ** 2))
        sizes = np.bincount(labels, minlength=ROLES) / len(sample)
        imbalance = float(np.sum(np.abs(sizes - 1 / ROLES)))
        score = inertia * (1 + imbalance)
        if best is None or score < best[0]:
            best = (score, centers)
    centers = best[1]
    labels = np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=2).argmin(axis=1)
    return centers, labels


def compute_pattern(frames: list[np.ndarray]) -> dict[str, Any] | None:
    if len(frames) < MIN_FRAMES_FOR_PATTERN:
        return None
    points = np.vstack(frames).astype(np.float32)
    if len(points) < ROLES * 5:
        return None
    centers, labels = best_roles(points)
    sizes = np.bincount(labels, minlength=ROLES)
    spreads = np.array(
        [
            np.std(points[labels == j], axis=0) if sizes[j] > 1 else np.array([3.0, 3.0])
            for j in range(ROLES)
        ]
    )
    lines = split_lines(centers[:, 0])
    formation = "-".join(str(len(g)) for g in lines)
    line_of = np.zeros(ROLES, dtype=int)
    for i, g in enumerate(lines):
        line_of[g] = i

    back = centers[lines[0]]
    front = centers[lines[-1]]
    line_height = float(np.mean(back[:, 0]))
    width = float(np.ptp(centers[:, 1]))
    depth = float(np.mean(front[:, 0]) - line_height)

    # Corredores do ponto de vista do time (atacando para a direita): esquerda = y pequeno.
    third = points[points[:, 0] > LENGTH * 2 / 3]
    corridors = None
    if len(third) >= 20:
        left = float(np.mean(third[:, 1] < WIDTH / 3))
        right = float(np.mean(third[:, 1] > 2 * WIDTH / 3))
        corridors = {"esquerda": round(left, 2), "centro": round(1 - left - right, 2), "direita": round(right, 2)}

    nx, ny = int(np.ceil(LENGTH / HEAT_CELL_M)), int(np.ceil(WIDTH / HEAT_CELL_M))
    heat, _, _ = np.histogram2d(
        np.clip(points[:, 0], 0, LENGTH - 1e-3),
        np.clip(points[:, 1], 0, WIDTH - 1e-3),
        bins=[nx, ny],
        range=[[0, LENGTH], [0, WIDTH]],
    )
    heat = heat / heat.max() if heat.max() > 0 else heat

    return {
        "formation": formation,
        "roles": [
            {
                "x": round(float(c[0]), 2),
                "y": round(float(c[1]), 2),
                "sx": round(float(s[0]), 2),
                "sy": round(float(s[1]), 2),
                "line": int(line_of[j]),
                "share": round(float(sizes[j]) / len(points), 3),
            }
            for j, (c, s) in enumerate(zip(centers, spreads))
        ],
        "lineHeight": round(line_height, 1),
        "block": describe_block(line_height),
        "width": round(width, 1),
        "depth": round(depth, 1),
        "corridors": corridors,
        "heat": {"nx": nx, "ny": ny, "cell": HEAT_CELL_M, "values": [round(float(v), 3) for v in heat.T.reshape(-1)]},
        "points": int(len(points)),
    }


class PatternStore:
    """Acumula posições por time e fase; sobrevive a novas capturas (só zera quando pedido)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.samples: dict[tuple[int, str], PhaseSamples] = {
                (t, p): PhaseSamples() for t in (0, 1) for p in PHASES
            }
            self.side = SideEstimator()
            self.possession: int | None = None
            self.possession_ts: float | None = None
            self.candidate: int | None = None
            self.candidate_frames = 0
            self.last_ts: float | None = None
            self.phase_frames = {"bola": 0, "avanço": 0, "sem fase": 0}
            self.cached: dict[str, Any] | None = None

    # ---------- um frame ----------

    def observe(self, field_map: dict[str, Any], ts: float) -> None:
        """Recebe o mapa do frame (jogadores em metros) quando a cena é de jogo ao vivo."""
        with self._lock:
            dt = 0.0 if self.last_ts is None else min(max(ts - self.last_ts, 0.0), 0.5)
            self.last_ts = ts
            players = [
                p
                for p in field_map.get("players", [])
                if p.get("t") in (0, 1) and (not p.get("g") or p.get("age", 0) <= GHOST_MAX_AGE_S)
            ]
            self._update_side(players, ts)
            team_pts = {
                t: np.array([[p["x"], p["y"]] for p in players if p["t"] == t and p["l"] in OUTFIELD_ROLES], np.float32)
                for t in (0, 1)
            }
            attacking = self._possession(field_map.get("ball"), players, team_pts, ts)
            if attacking is None:
                self.phase_frames["sem fase"] += 1
                return
            defends_left0 = self.side.team0_defends_left()
            if defends_left0 is None:
                self.phase_frames["sem fase"] += 1
                return
            for t in (0, 1):
                pts = team_pts[t]
                if len(pts) < MIN_PLAYERS_PER_FRAME:
                    continue
                defends_left = defends_left0 if t == 0 else not defends_left0
                phase = "ataque" if t == attacking else "defesa"
                bucket = self.samples[(t, phase)]
                bucket.frames.append(normalize(pts, defends_left))
                bucket.seconds += dt

    def _update_side(self, players: list[dict[str, Any]], ts: float) -> None:
        evidence = 0.0
        for p in players:
            if p["l"] == "goleiro" and not p.get("g"):
                left = p["x"] < LENGTH / 2
                evidence += 3.0 if (left == (p["t"] == 0)) else -3.0
        xs = {t: [p["x"] for p in players if p["t"] == t and p["l"] in OUTFIELD_ROLES] for t in (0, 1)}
        if len(xs[0]) >= 3 and len(xs[1]) >= 3:
            # Fraco: quem fica mais atrás no geral tende a defender aquele lado.
            evidence += 0.2 if np.mean(xs[0]) < np.mean(xs[1]) else -0.2
        if evidence:
            self.side.add(evidence, ts)

    def _possession(
        self, ball: dict[str, Any] | None, players: list[dict[str, Any]], team_pts: dict[int, np.ndarray], ts: float
    ) -> int | None:
        seen = [p for p in players if not p.get("g")]
        owner = None
        if ball is not None and not ball.get("e") and seen:
            d = [np.hypot(p["x"] - ball["x"], p["y"] - ball["y"]) for p in seen]
            i = int(np.argmin(d))
            if d[i] <= POSSESSION_RADIUS_M:
                owner = seen[i]["t"]
        if owner is not None:
            if owner == self.candidate:
                self.candidate_frames += 1
            else:
                self.candidate, self.candidate_frames = owner, 1
            if self.candidate_frames >= POSSESSION_CONFIRM_FRAMES:
                self.possession = owner
                self.possession_ts = ts
            if self.possession is not None:
                self.phase_frames["bola"] += 1
                return self.possession

        recent = (
            self.possession
            if self.possession_ts is not None and ts - self.possession_ts <= POSSESSION_MEMORY_S
            else None
        )
        if recent is not None:
            self.phase_frames["bola"] += 1
            return recent

        # Sem bola: o time mais avançado em direção ao gol adversário está atacando.
        defends_left0 = self.side.team0_defends_left()
        if defends_left0 is None or len(team_pts[0]) < 3 or len(team_pts[1]) < 3:
            return None
        adv0 = float(np.mean(team_pts[0][:, 0])) if defends_left0 else LENGTH - float(np.mean(team_pts[0][:, 0]))
        adv1 = LENGTH - float(np.mean(team_pts[1][:, 0])) if defends_left0 else float(np.mean(team_pts[1][:, 0]))
        if abs(adv0 - adv1) < TILT_MIN_DIFF_M:
            return None
        self.phase_frames["avanço"] += 1
        return 0 if adv0 > adv1 else 1

    # ---------- resumo ----------

    def summary(self) -> dict[str, Any]:
        with self._lock:
            frames = {key: list(bucket.frames) for key, bucket in self.samples.items()}
            seconds = {key: bucket.seconds for key, bucket in self.samples.items()}
            side = self.side.team0_defends_left()
            phase_frames = dict(self.phase_frames)
        out: dict[str, Any] = {"options": {}, "phaseSource": phase_frames, "team0DefendsLeft": side}
        for (t, phase), f in frames.items():
            pattern = compute_pattern(f)
            out["options"][f"{t}-{phase}"] = {
                "team": t,
                "phase": phase,
                "frames": len(f),
                "seconds": round(seconds[(t, phase)], 1),
                "needed": MIN_FRAMES_FOR_PATTERN,
                "pattern": pattern,
            }
        self.cached = out
        return out
