"""Como o time se movimenta dentro de cada fase (o "campinho de movimentação").

O padrão mostra onde cada posição fica em média. Aqui os mesmos momentos são
divididos em três etapas pela altura do time no campo:

- **ataque**: saída (time mais recuado) → progressão → chegada (time mais avançado);
- **defesa**: pressão alta (time mais adiantado) → bloco médio → bloco baixo.

Em cada etapa, as 10 posições do padrão são reajustadas só com os momentos dela
(k-means começando das posições médias, deslocadas para a altura da etapa, para
cada posição continuar sendo a mesma). O caminho de cada posição pelas três
etapas mostra a intenção do time: o lateral que sobe e fecha para o meio, o
volante que cai entre os zagueiros na saída, o ponta que recompõe e faz a linha
de 5 quando o time se fecha.

Limite: a câmera mostra só uma parte do campo, então em cada etapa as posições
longe da bola têm menos dados. Essas saem marcadas como "estimadas".
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .pitch import LENGTH, WIDTH

STAGES = {
    "ataque": ("Saída de bola", "Progressão", "Chegada"),
    "defesa": ("Pressão alta", "Bloco médio", "Bloco baixo"),
}
MIN_STAGE_FRAMES = 30
MIN_PLAYERS = 5
MAX_STAGE_FRAMES = 200  # momentos sorteados por etapa (o casamento é feito momento a momento)
MAX_ASSIGN_DIST_M = 22.0
ESTIMATED_SHARE = 0.035  # menos que isso dos pontos da etapa (o normal é ~10%): posição estimada
BACK_BAND_M = 6.0

SIDE_WORDS = {"LE", "LD", "ALE", "ALD", "ME", "MD", "PE", "PD"}


def _stage_roles(frames: list[np.ndarray], start: np.ndarray, iters: int = 4) -> tuple[np.ndarray, np.ndarray]:
    """Reajusta as posições com os momentos de uma etapa; devolve os centros e a fração de pontos de cada um.

    Em cada momento, cada jogador visto vai para uma posição diferente (casamento de menor custo),
    então duas posições não disputam o mesmo jogador e cada uma continua sendo a mesma pessoa.
    """
    from scipy.optimize import linear_sum_assignment

    centers = start.astype(np.float64).copy()
    k = len(centers)
    shares = np.zeros(k)
    total = max(1, sum(len(f) for f in frames))
    for _ in range(iters):
        sums = np.zeros((k, 2))
        counts = np.zeros(k)
        for f in frames:
            dist = np.linalg.norm(f[:, None, :] - centers[None, :, :], axis=2)
            # Coluna extra por jogador: ficar sem posição custa o limite (jogador longe de tudo).
            cost = np.hstack([dist, np.full((len(f), len(f)), MAX_ASSIGN_DIST_M)])
            rows, cols = linear_sum_assignment(cost)
            keep = cols < k
            np.add.at(sums, cols[keep], f[rows[keep]])
            np.add.at(counts, cols[keep], 1)
        moved = counts >= 5
        centers[moved] = sums[moved] / counts[moved, None]
        shares = counts / total
    return centers, shares


def back_line(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Posições que formam a última linha nesta etapa (até 6 m do mais recuado), da esquerda para a direita."""
    seen = [r for r in roles if not r.get("estimated")]
    if len(seen) >= 5:
        roles = seen  # posição sem dados nesta etapa não decide a linha
    deepest = min(r["x"] for r in roles)
    return sorted((r for r in roles if r["x"] <= deepest + BACK_BAND_M), key=lambda r: r["y"])


def team_flow(frames: list[np.ndarray], pattern: dict[str, Any] | None, phase: str) -> dict[str, Any] | None:
    """Três etapas da fase, com a posição de cada uma das 10 posições do padrão em cada etapa."""
    if not pattern or phase not in STAGES:
        return None
    valid = [f for f in frames if len(f) >= MIN_PLAYERS]
    if len(valid) < 3 * MIN_STAGE_FRAMES:
        return None
    heights = np.array([float(np.mean(f[:, 0])) for f in valid])
    order = np.argsort(heights)
    if phase == "defesa":
        order = order[::-1]  # da pressão alta (time adiantado) ao bloco baixo
    chunks = np.array_split(order, 3)
    roles = pattern["roles"]
    centers = np.array([[r["x"], r["y"]] for r in roles], dtype=np.float64)
    overall_x = float(np.mean(np.vstack(valid)[:, 0]))
    rng = np.random.default_rng(0)

    def frames_of(idx: np.ndarray) -> list[np.ndarray]:
        if len(idx) > MAX_STAGE_FRAMES:
            idx = rng.choice(idx, MAX_STAGE_FRAMES, replace=False)
        return [valid[i].astype(np.float64) for i in idx]

    def shifted(base: np.ndarray, frames: list[np.ndarray], ref_x: float) -> np.ndarray:
        start = base.copy()
        mean_x = float(np.mean(np.vstack(frames)[:, 0]))
        start[:, 0] = np.clip(start[:, 0] + mean_x - ref_x, 1.0, LENGTH - 1.0)
        return start

    # Começa pela etapa do meio (a mais parecida com a média) e segue para as pontas,
    # cada uma partindo da vizinha: assim cada posição continua sendo a mesma nas três.
    picked = [frames_of(idx) for idx in chunks]
    mid_x = float(np.mean(np.vstack(picked[1])[:, 0]))
    results: list[tuple[np.ndarray, np.ndarray]] = [None, None, None]  # type: ignore[list-item]
    results[1] = _stage_roles(picked[1], shifted(centers, picked[1], overall_x))
    for i in (0, 2):
        results[i] = _stage_roles(picked[i], shifted(results[1][0], picked[i], mid_x))

    stages = []
    for name, idx, (stage_centers, shares) in zip(STAGES[phase], chunks, results):
        stages.append({
            "name": name,
            "height": round(float(np.mean(heights[idx])), 1),
            "frames": int(len(idx)),
            "roles": [
                {
                    "x": round(float(c[0]), 1),
                    "y": round(float(c[1]), 1),
                    "name": roles[j].get("name", ""),
                    "line": roles[j]["line"],
                    "estimated": bool(shares[j] < ESTIMATED_SHARE),
                }
                for j, c in enumerate(stage_centers)
            ],
        })
    return {"phase": phase, "stages": stages, "notes": flow_notes(stages, phase)}


def _side(y: float) -> str:
    if y < WIDTH / 2 - 8:
        return "esquerda"
    if y > WIDTH / 2 + 8:
        return "direita"
    return "centro"


def _at(stage: str) -> str:
    return f"{'no' if stage.startswith('Bloco') else 'na'} {stage.lower()}"


def _names(group: list[dict[str, Any]]) -> str:
    return ", ".join(r["name"] or "?" for r in group)


def flow_notes(stages: list[dict[str, Any]], phase: str) -> list[str]:
    """Frases curtas sobre o que muda da primeira para a última etapa."""
    first, last = stages[0], stages[-1]
    notes: list[str] = []

    # Última linha em cada etapa: saída com 3, linha de 5 no bloco baixo...
    backs = [back_line(s["roles"]) for s in stages]
    sizes = [len(b) for b in backs]
    # Quem não é defensor e aparece na última linha: volante que cai na saída, ponta que recompõe.
    key = 0 if phase == "ataque" else len(stages) - 1
    extra = [r for r in backs[key] if r["line"] > 0 and not r["estimated"]]
    if extra:
        who = ", ".join(r["name"] or "?" for r in extra)
        if phase == "ataque":
            notes.append(f"Na saída de bola, {who} cai na linha dos zagueiros e a saída sai com {sizes[0]}.")
        else:
            notes.append(f"No bloco baixo, {who} entra na última linha, que fica com {sizes[-1]}.")
    if len(set(sizes)) > 1:
        parts = [f"{n} {_at(s['name'])}" for n, s in zip(sizes, stages)]
        notes.append(f"Última linha: {', '.join(parts)} ({_names(backs[0])} → {_names(backs[-1])}).")
    else:
        notes.append(f"A última linha fica com {sizes[0]} nas três etapas ({_names(backs[-1])}).")

    shift = float(np.mean([b["x"] - a["x"] for a, b in zip(first["roles"], last["roles"])]))
    if phase == "ataque":
        notes.append(f"Da saída à chegada o time sobe em média {max(shift, 0):.0f} m.")
    else:
        notes.append(f"Da pressão alta ao bloco baixo o time recua em média {max(-shift, 0):.0f} m.")

    moves = []
    for a, b in zip(first["roles"], last["roles"]):
        if a["estimated"] and b["estimated"]:
            continue
        name = a["name"] or "?"
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        rel = dx - shift
        side = _side(a["y"])
        inward = (dy > 0 and side == "esquerda") or (dy < 0 and side == "direita")
        text = None
        if phase == "ataque":
            if rel >= 8:
                text = f"{name} sobe {dx:.0f} m ({rel:.0f} m a mais que o time)"
            elif rel <= -7 and a["line"] > 0:
                text = f"{name} segura a posição: sobe só {max(dx, 0):.0f} m"
        else:
            if rel <= -7:
                text = f"{name} recua {-dx:.0f} m ({-rel:.0f} m a mais que o time)"
            elif rel >= 7:
                text = f"{name} fica adiantado: recua só {max(-dx, 0):.0f} m"
        lateral = None
        if abs(dy) >= 6:
            if side == "centro":
                lateral = f"abre para a {'direita' if dy > 0 else 'esquerda'} ({abs(dy):.0f} m)"
            else:
                lateral = f"{'fecha para o meio' if inward else 'abre para a linha lateral'} ({abs(dy):.0f} m)"
        if text and lateral:
            moves.append((abs(rel) + abs(dy), f"{text} e {lateral}."))
        elif text:
            moves.append((abs(rel), f"{text}."))
        elif lateral and (name in SIDE_WORDS or abs(dy) >= 9):
            moves.append((abs(dy), f"{name} {lateral}."))
    moves.sort(key=lambda m: -m[0])
    notes.extend(m[1] for m in moves[:4])
    return notes


# ---------------------------------------------------------------------------
# Setas do campinho: só os passes e cruzamentos que mais se repetem
# ---------------------------------------------------------------------------

PASS_ZONES_X = 6  # faixas de 17,5 m
PASS_ZONES_Y = 3  # esquerda, centro, direita
MIN_REPEATS_PASS = 3
MIN_REPEATS_CROSS = 2
TOP_PASSES = 3


def _zone(x: float, y: float) -> tuple[int, int]:
    zx = min(PASS_ZONES_X - 1, max(0, int(x / (LENGTH / PASS_ZONES_X))))
    zy = min(PASS_ZONES_Y - 1, max(0, int(y / (WIDTH / PASS_ZONES_Y))))
    return zx, zy


def _arrow(group: list[tuple[float, float, float, float]], kind: str) -> dict[str, Any]:
    arr = np.array(group, dtype=np.float64)
    x0, y0, x1, y1 = arr.mean(axis=0)
    return {"kind": kind, "from": [round(x0, 1), round(y0, 1)], "to": [round(x1, 1), round(y1, 1)], "count": len(group)}


def ball_arrows(
    passes: list[tuple[float, int, float, float, float, float]],
    crosses: list[tuple[float, int, float, float, float, float]],
    team: int,
) -> list[dict[str, Any]]:
    """Os passes mais repetidos (de uma zona do campo para outra) e os cruzamentos de cada lado.

    Coordenadas do time atacando para a direita. Passes dentro da mesma zona não viram seta
    (são toques curtos que só poluiriam o desenho).
    """
    groups: dict[tuple[tuple[int, int], tuple[int, int]], list[tuple[float, float, float, float]]] = {}
    for _, t, x0, y0, x1, y1 in passes:
        if t != team:
            continue
        a, b = _zone(x0, y0), _zone(x1, y1)
        if a == b:
            continue
        groups.setdefault((a, b), []).append((x0, y0, x1, y1))
    ranked = sorted(groups.values(), key=len, reverse=True)
    out = [_arrow(g, "passe") for g in ranked[:TOP_PASSES] if len(g) >= MIN_REPEATS_PASS]
    for side in ("esquerda", "direita"):
        mine = [
            (x0, y0, x1, y1)
            for _, t, x0, y0, x1, y1 in crosses
            if t == team and ((y0 < WIDTH / 2) == (side == "esquerda"))
        ]
        if len(mine) >= MIN_REPEATS_CROSS:
            out.append(_arrow(mine, "cruzamento"))
    return out
