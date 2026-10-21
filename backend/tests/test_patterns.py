"""Testes dos padrões dos times com formações sintéticas."""

from __future__ import annotations

import numpy as np

from app.patterns import PatternStore, compute_pattern, normalize, split_lines

# Posições médias (time atacando para a direita, metros).
F442 = [(25, 10), (22, 26), (22, 42), (25, 58), (45, 10), (42, 28), (42, 40), (45, 58), (65, 28), (65, 40)]
F532 = [(20, 8), (16, 22), (15, 34), (16, 46), (20, 60), (38, 20), (36, 34), (38, 48), (58, 28), (58, 40)]


def frames_from(shape, n=200, visible=7, noise=1.5, seed=0):
    rng = np.random.default_rng(seed)
    base = np.array(shape, dtype=np.float32)
    frames = []
    for _ in range(n):
        idx = rng.choice(len(base), size=visible, replace=False)
        frames.append(base[idx] + rng.normal(0, noise, (visible, 2)).astype(np.float32))
    return frames


def test_split_lines_finds_back_middle_front():
    xs = np.array([p[0] for p in F442], dtype=np.float32)
    lines = split_lines(xs)
    assert [len(g) for g in lines] == [4, 4, 2]


def test_split_lines_four_lines_and_football_limits():
    f4231 = np.array([22, 20, 20, 22, 38, 38, 52, 54, 52, 66], dtype=np.float32)
    assert [len(g) for g in split_lines(f4231)] == [4, 2, 3, 1]
    # Duas posições bem recuadas não viram uma "defesa de 2": a defesa tem de 3 a 5.
    odd = np.array([20, 21, 27, 28, 28, 40, 41, 42, 60, 61], dtype=np.float32)
    assert 3 <= len(split_lines(odd)[0]) <= 5


def test_compute_pattern_recovers_formations():
    p442 = compute_pattern(frames_from(F442))
    assert p442["formation"] == "4-4-2"
    assert 20 < p442["lineHeight"] < 27
    assert p442["block"] == "baixo"
    p532 = compute_pattern(frames_from(F532, seed=3))
    assert p532["formation"] == "5-3-2"
    assert len(p532["heat"]["values"]) == p532["heat"]["nx"] * p532["heat"]["ny"]


def test_too_few_frames_gives_no_pattern():
    assert compute_pattern(frames_from(F442, n=10)) is None


def test_normalize_rotates_team_defending_right():
    pts = np.array([[100.0, 10.0]], dtype=np.float32)
    assert np.allclose(normalize(pts, defends_left=False), [[5.0, 58.0]])
    assert np.allclose(normalize(pts, defends_left=True), pts)


def mirrored(shape):
    return [(105 - x, 68 - y) for x, y in shape]


def test_store_separates_attack_and_defense_and_sides():
    store = PatternStore()
    rng = np.random.default_rng(7)
    # Time 0 defende a esquerda e ataca num 4-4-2; time 1 defende a direita num 5-3-2 (no campo real, espelhado).
    for i in range(160):
        ts = i * 0.15
        players = [{"x": 3.0, "y": 34.0, "t": 0, "l": "goleiro", "g": False, "age": 0}]
        players.append({"x": 102.0, "y": 34.0, "t": 1, "l": "goleiro", "g": False, "age": 0})
        for x, y in F442:
            players.append({"x": x + 10 + rng.normal(0, 1), "y": y + rng.normal(0, 1), "t": 0, "l": "jogador", "g": False, "age": 0})
        for x, y in mirrored(F532):
            players.append({"x": x + rng.normal(0, 1), "y": y + rng.normal(0, 1), "t": 1, "l": "jogador", "g": False, "age": 0})
        holder = players[3]  # um jogador do time 0 com a bola
        ball = {"x": holder["x"] + 0.5, "y": holder["y"], "e": False}
        store.observe({"players": players, "ball": ball}, ts)

    summary = store.summary()
    assert summary["team0DefendsLeft"] is True
    attack0 = summary["options"]["0-ataque"]
    defense1 = summary["options"]["1-defesa"]
    assert attack0["pattern"]["formation"] == "4-4-2"
    assert defense1["pattern"]["formation"] == "5-3-2"
    # Depois de girado, o time 1 também "ataca para a direita": a defesa dele fica perto de x = 15.
    assert defense1["pattern"]["lineHeight"] < 25
    assert summary["options"]["0-defesa"]["pattern"] is None
    assert summary["phaseSource"]["bola"] > 100

    store.reset()
    assert store.summary()["options"]["0-ataque"]["frames"] == 0
