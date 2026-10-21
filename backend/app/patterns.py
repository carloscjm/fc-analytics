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


# Formações que existem no futebol (de trás para a frente) e quanto cada uma é rara.
# Um custo maior pede que as posições se encaixem bem melhor para ela ganhar.
FORMATIONS: dict[tuple[int, ...], float] = {
    (4, 4, 2): 0.0,
    (4, 3, 3): 0.0,
    (4, 2, 3, 1): 0.1,
    (4, 5, 1): 0.25,
    (3, 5, 2): 0.25,
    (5, 3, 2): 0.25,
    (4, 1, 4, 1): 0.35,
    (3, 4, 3): 0.35,
    (5, 4, 1): 0.35,
    (4, 4, 1, 1): 0.4,
    (4, 3, 2, 1): 0.45,
    (3, 4, 2, 1): 0.5,
    (3, 4, 1, 2): 0.5,
    (4, 2, 2, 2): 0.6,
    (4, 1, 3, 2): 0.6,
}
FORMATION_PRIOR_WEIGHT = 0.12


def split_lines(xs: np.ndarray) -> list[list[int]]:
    """Divide as 10 posições em linhas, de trás para a frente, numa formação conhecida.

    Para cada formação da lista, as posições (ordenadas pela profundidade) são
    cortadas nos tamanhos dela. O custo é a variação de profundidade dentro das
    linhas, em relação à variação total, mais o quanto a formação é rara. Assim
    posições médias confusas (a câmera não mostra o campo todo) caem numa formação
    comum em vez de nomes que não existem, como 3-3-2-2.
    """
    order = np.argsort(xs)
    sorted_x = xs[order]
    n = len(sorted_x)
    total = float(np.var(sorted_x)) * n
    if n != 10 or total <= 1e-6:
        return [list(order)]
    best: tuple[float, list[list[int]]] | None = None
    for sizes, prior in FORMATIONS.items():
        bounds = np.cumsum((0, *sizes))
        within = sum(float(np.var(sorted_x[bounds[i] : bounds[i + 1]])) * sizes[i] for i in range(len(sizes)))
        cost = within / total + FORMATION_PRIOR_WEIGHT * prior
        if best is None or cost < best[0]:
            best = (cost, [list(order[bounds[i] : bounds[i + 1]]) for i in range(len(sizes))])
    return best[1]

# ---------------------------------------------------------------------------
# Nome de cada posição (o time sempre atacando para a direita; y pequeno = lado esquerdo do time)
# ---------------------------------------------------------------------------


def _names_for_line(n: int, kind: str, back_three: bool) -> list[str]:
    """Nomes da esquerda para a direita, por tipo de linha."""
    if kind == "defesa":
        return {3: ["ZAG"] * 3, 4: ["LE", "ZAG", "ZAG", "LD"], 5: ["LE", "ZAG", "ZAG", "ZAG", "LD"]}.get(n, ["ZAG"] * n)
    if kind == "ataque":
        return {1: ["CA"], 2: ["CA", "CA"], 3: ["PE", "CA", "PD"]}.get(n, ["ATA"] * n)
    if kind == "meia":  # segunda linha do meio (mais avançada) nas formações de 4 linhas
        return {1: ["MEI"], 2: ["MEI", "MEI"], 3: ["PE", "MEI", "PD"], 4: ["ME", "MEI", "MEI", "MD"]}.get(n, ["MEI"] * n)
    # meio-campo
    wide_left, wide_right = ("ALE", "ALD") if back_three else ("ME", "MD")
    return {
        1: ["VOL"],
        2: ["VOL", "VOL"],
        3: ["MC", "MC", "MC"],
        4: [wide_left, "MC", "MC", wide_right],
        5: [wide_left, "MC", "MC", "MC", wide_right],
    }.get(n, ["MC"] * n)


def name_roles(centers: np.ndarray, lines: list[list[int]]) -> list[str]:
    """GOL fica de fora (só jogadores de linha): LE, ZAG, LD, VOL, MC, ME, MD, MEI, PE, PD, CA..."""
    names = [""] * len(centers)
    k = len(lines)
    back_three = len(lines[0]) == 3
    for i, group in enumerate(lines):
        if i == 0:
            kind = "defesa"
        elif i == k - 1:
            kind = "ataque"
        elif k == 4 and i == 2:
            kind = "meia"
        else:
            kind = "meio"
        order = sorted(group, key=lambda j: centers[j][1])
        labels = _names_for_line(len(order), kind, back_three)
        for j, label in zip(order, labels):
            names[j] = label
        # No meio-campo de 3 ou 5, o mais recuado entre os centrais é o volante.
        if kind == "meio" and len(order) in (3, 5):
            central = [j for j in order if names[j] == "MC"]
            if central:
                names[min(central, key=lambda j: centers[j][0])] = "VOL"
    return names


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
    role_names = name_roles(centers, lines)

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
                "name": role_names[j],
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
        out["transitions"] = {
            str(t): transition(out["options"][f"{t}-defesa"]["pattern"], out["options"][f"{t}-ataque"]["pattern"])
            for t in (0, 1)
        }
        self.cached = out
        return out


# ---------------------------------------------------------------------------
# Defesa → ataque: para onde cada posição vai quando o time recupera a bola
# ---------------------------------------------------------------------------

LINE_CHANGE_COST = 8.0
SIDE_NAMES = {"LE": "lateral esquerdo", "LD": "lateral direito", "ALE": "ala esquerdo", "ALD": "ala direito"}


def transition(defense: dict[str, Any] | None, attack: dict[str, Any] | None) -> dict[str, Any] | None:
    """Liga cada posição da defesa à posição mais provável no ataque e descreve os movimentos que chamam atenção.

    As posições médias de cada fase são grupos de pontos, não jogadores com nome; a ligação
    usa o lado do campo, a profundidade e a linha de cada posição (a mais barata no total).
    """
    if not defense or not attack:
        return None
    from scipy.optimize import linear_sum_assignment

    d_roles, a_roles = defense["roles"], attack["roles"]
    d_lines = max(r["line"] for r in d_roles) or 1
    a_lines = max(r["line"] for r in a_roles) or 1
    cost = np.zeros((len(d_roles), len(a_roles)))
    for i, d in enumerate(d_roles):
        for j, a in enumerate(a_roles):
            cost[i, j] = (
                abs(d["y"] - a["y"])
                + 0.35 * abs(d["x"] - a["x"])
                + LINE_CHANGE_COST * abs(d["line"] / d_lines - a["line"] / a_lines)
            )
    rows, cols = linear_sum_assignment(cost)
    moves = []
    sectors = ("defesa", "meio", "ataque")
    for i, j in zip(rows, cols):
        d, a = d_roles[i], a_roles[j]
        line_kind = 0 if a["line"] == 0 else (2 if a["line"] == a_lines else 1)
        attack_name = a.get("name", "")
        # A posição se reconhece melhor pela forma de defender: no ataque ela leva o mesmo nome
        # (o lateral que sobe até o meio continua "LE", não vira "VOL").
        if d.get("name"):
            a["name"] = d["name"]
        moves.append({
            "name": d.get("name", ""),
            "attackName": attack_name,
            "attackSector": sectors[line_kind],
            "from": [d["x"], d["y"]],
            "to": [a["x"], a["y"]],
            "dx": round(a["x"] - d["x"], 1),
            "dy": round(a["y"] - d["y"], 1),
        })
    shift = float(np.mean([m["dx"] for m in moves]))
    return {"moves": moves, "teamShift": round(shift, 1), "highlights": highlights(moves, shift, attack)}


def highlights(moves: list[dict[str, Any]], shift: float, attack: dict[str, Any]) -> list[str]:
    """Frases curtas sobre os movimentos mais claros (laterais, volantes, pontas)."""
    out: list[str] = []
    if shift >= 3:
        out.append(f"O time inteiro avança em média {shift:.0f} m quando passa da defesa para o ataque.")
    elif shift <= -3:
        out.append(f"O time fica em média {-shift:.0f} m mais recuado quando ataca do que quando defende (contra-ataque ou dados ainda poucos).")
    else:
        out.append("O time fica praticamente na mesma altura quando ataca e quando defende.")
    for m in sorted(moves, key=lambda m: -abs(m["dx"] - shift)):
        name, rel = m["name"], m["dx"] - shift
        if name in SIDE_NAMES:
            who = SIDE_NAMES[name]
            if rel >= 6:
                out.append(f"O {who} ({name}) sobe {m['dx']:.0f} m: apoia o ataque, {rel:.0f} m a mais que o resto do time.")
            elif rel <= -4:
                out.append(f"O {who} ({name}) fica: avança só {max(m['dx'], 0):.0f} m e compõe a defesa quando o time ataca.")
        elif name in ("PE", "PD"):
            inward = (m["dy"] > 0) if name == "PE" else (m["dy"] < 0)
            if abs(m["dy"]) >= 6:
                side = "fecha para o meio" if inward else "abre pela ponta"
                out.append(f"O ponta {'esquerdo' if name == 'PE' else 'direito'} ({name}) {side} no ataque ({abs(m['dy']):.0f} m).")
    # Volante que cai entre os zagueiros na saída de bola: no ataque, fica na altura da defesa e pelo meio.
    back = [r for r in attack["roles"] if r["line"] == 0]
    if back:
        back_x = float(np.mean([r["x"] for r in back]))
        for m in moves:
            if m["name"] == "VOL" and abs(m["to"][0] - back_x) <= 6 and abs(m["to"][1] - WIDTH / 2) <= 12:
                out.append("O volante (VOL) recua para perto dos zagueiros quando o time tem a bola: ajuda na saída de bola.")
                break
    return out[:5]
