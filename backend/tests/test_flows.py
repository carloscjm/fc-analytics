"""Testes do campinho de movimentação (etapas de cada fase)."""

from __future__ import annotations

import numpy as np

from app.flows import back_line, team_flow
from app.patterns import compute_pattern

# 4-3-3 atacando para a direita. Na saída o VOL cai entre os zagueiros e os laterais ficam;
# na chegada os laterais sobem muito e o LE fecha para o meio.
BUILD = [(20, 8), (18, 26), (17, 34), (18, 42), (20, 60), (36, 26), (36, 42), (50, 10), (55, 34), (50, 58)]
MID = [(30, 8), (28, 26), (36, 34), (28, 42), (30, 60), (48, 26), (48, 42), (62, 10), (66, 34), (62, 58)]
FINAL = [(62, 20), (40, 26), (52, 34), (40, 42), (60, 60), (62, 26), (62, 42), (78, 12), (84, 34), (78, 56)]
# índice:  LE       ZAG       VOL       ZAG       LD        MC        MC        PE        CA        PD


def stage_frames(shape, n, seed):
    rng = np.random.default_rng(seed)
    base = np.array(shape, dtype=np.float32)
    frames = []
    for _ in range(n):
        idx = rng.choice(len(base), size=8, replace=False)
        frames.append(base[idx] + rng.normal(0, 1.2, (8, 2)).astype(np.float32))
    return frames


def test_flow_follows_each_role_through_the_stages():
    frames = stage_frames(BUILD, 150, 1) + stage_frames(MID, 150, 2) + stage_frames(FINAL, 150, 3)
    pattern = compute_pattern(frames)
    flow = team_flow(frames, pattern, "ataque")
    assert flow is not None
    assert [s["name"] for s in flow["stages"]] == ["Saída de bola", "Progressão", "Chegada"]
    first, last = flow["stages"][0], flow["stages"][-1]
    assert first["height"] < last["height"]
    # A posição que começa na lateral esquerda (perto de 20, 8) termina subindo e fechando.
    j = min(range(10), key=lambda i: np.hypot(first["roles"][i]["x"] - 20, first["roles"][i]["y"] - 8))
    assert last["roles"][j]["x"] > 50 and last["roles"][j]["y"] > 14
    # Saída com 4 atrás (LE/LD ficam ~3 m à frente dos 3 centrais), na chegada só 2 zagueiros.
    assert len(back_line(last["roles"])) == 2
    assert any("Última linha" in n for n in flow["notes"])


def test_flow_needs_enough_moments_and_a_pattern():
    frames = stage_frames(BUILD, 40, 1)
    assert team_flow(frames, compute_pattern(frames), "ataque") is None
    assert team_flow(stage_frames(BUILD, 200, 1), None, "ataque") is None


def test_defense_goes_from_high_press_to_low_block():
    high = [(45, 10), (42, 26), (42, 42), (45, 58), (62, 12), (60, 28), (60, 40), (62, 56), (78, 28), (78, 40)]
    low = [(14, 8), (12, 22), (11, 34), (12, 46), (14, 60), (28, 12), (26, 28), (26, 40), (28, 56), (44, 34)]
    frames = stage_frames(high, 150, 4) + stage_frames(high, 150, 5) + stage_frames(low, 150, 6)
    flow = team_flow(frames, compute_pattern(frames), "defesa")
    assert flow is not None
    assert [s["name"] for s in flow["stages"]] == ["Pressão alta", "Bloco médio", "Bloco baixo"]
    assert flow["stages"][0]["height"] > flow["stages"][-1]["height"]
    assert any("recua" in n for n in flow["notes"])
