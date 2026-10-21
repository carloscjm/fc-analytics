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


def test_ball_arrows_keep_only_repeated_passes_and_crosses():
    from app.flows import ball_arrows

    passes = [(i, 0, 20.0, 10.0, 45.0, 12.0) for i in range(5)]  # LE → ME, 5 vezes
    passes += [(i, 0, 40.0, 30.0, 70.0, 34.0) for i in range(2)]  # só 2: não vira seta
    passes += [(i, 0, 30.0, 30.0, 33.0, 32.0) for i in range(9)]  # mesma zona: toque curto
    passes += [(i, 1, 20.0, 10.0, 45.0, 12.0) for i in range(9)]  # outro time
    crosses = [(i, 0, 90.0, 6.0, 98.0, 32.0) for i in range(3)] + [(9, 0, 90.0, 62.0, 97.0, 36.0)]
    arrows = ball_arrows(passes, crosses, 0)
    kinds = [(a["kind"], a["count"]) for a in arrows]
    assert kinds == [("passe", 5), ("cruzamento", 3)]
    assert arrows[0]["from"] == [20.0, 10.0] and arrows[0]["to"] == [45.0, 12.0]


def test_pattern_store_records_passes_between_teammates():
    from app.patterns import PatternStore

    store = PatternStore()
    store.side.score = 10.0  # time 0 defende a esquerda
    store.possession, store.by_ball = 0, True
    a = {"id": 1, "x": 30.0, "y": 20.0, "t": 0, "l": "jogador", "g": False, "age": 0}
    b = {"id": 2, "x": 50.0, "y": 25.0, "t": 0, "l": "jogador", "g": False, "age": 0}
    store._track_pass([a, b], {"x": 30.5, "y": 20.0}, 0, 30.5, 20.0, 100.0)
    store._track_pass([a, b], {"x": 49.5, "y": 25.0}, 0, 49.5, 25.0, 101.5)
    assert list(store.passes) == [(101.5, 0, 30.5, 20.0, 49.5, 25.0)]
