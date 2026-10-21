"""Testes dos padrões dos times com formações sintéticas."""

from __future__ import annotations

import numpy as np
import pytest

from app.patterns import FORMATIONS, PatternStore, compute_pattern, normalize, split_lines

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


def test_split_lines_always_gives_a_known_formation():
    # Posições confusas (espalhadas por igual) ainda dão uma formação que existe.
    rng = np.random.default_rng(11)
    for _ in range(50):
        xs = rng.uniform(15, 85, 10).astype(np.float32)
        assert tuple(len(g) for g in split_lines(xs)) in FORMATIONS


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


def test_position_names():
    from app.patterns import name_roles

    c442 = np.array(F442, dtype=np.float32)
    assert sorted(name_roles(c442, split_lines(c442[:, 0]))) == sorted(["LE", "ZAG", "ZAG", "LD", "ME", "MC", "MC", "MD", "CA", "CA"])
    f4231 = np.array([(22, 8), (20, 26), (20, 42), (22, 60), (38, 28), (38, 40), (54, 10), (52, 34), (54, 58), (66, 34)], dtype=np.float32)
    names = name_roles(f4231, split_lines(f4231[:, 0]))
    assert names == ["LE", "ZAG", "ZAG", "LD", "VOL", "VOL", "PE", "MEI", "PD", "CA"]
    c532 = np.array(F532, dtype=np.float32)
    assert name_roles(c532, split_lines(c532[:, 0]))[:5] == ["LE", "ZAG", "ZAG", "ZAG", "LD"]


def test_transition_finds_the_fullback_going_up():
    from app.patterns import name_roles, transition

    def pattern(points):
        c = np.array(points, dtype=np.float32)
        lines = split_lines(c[:, 0])
        line_of = {j: i for i, g in enumerate(lines) for j in g}
        names = name_roles(c, lines)
        return {"roles": [{"x": float(x), "y": float(y), "line": line_of[j], "name": names[j]} for j, (x, y) in enumerate(c)]}

    defense = pattern(F442)
    # No ataque o time sobe 15 m; o lateral esquerdo sobe 28 m (sem passar o meia) e o direito fica.
    attack_pts = [(x + 15, y) for x, y in F442]
    attack_pts[0] = (F442[0][0] + 28, F442[0][1])
    attack_pts[3] = (F442[3][0] + 3, F442[3][1])
    result = transition(defense, pattern(attack_pts))
    by_name = {m["name"]: m for m in result["moves"] if m["name"] in ("LE", "LD")}
    assert by_name["LE"]["dx"] == 28 and by_name["LD"]["dx"] == 3
    text = " ".join(result["highlights"])
    assert "lateral esquerdo (LE) sobe 28 m" in text
    assert "lateral direito (LD) fica" in text
    assert transition(defense, None) is None
    # No padrão de ataque, cada posição fica com o nome que tem na defesa.
    attack = pattern(attack_pts)
    transition(defense, attack)
    le = max(attack["roles"], key=lambda r: r["x"] if r["y"] < 15 and r["line"] < 2 else -1)
    assert sorted(r["name"] for r in attack["roles"]) == sorted(r["name"] for r in defense["roles"])


F343 = [(20, 18), (18, 34), (20, 50), (38, 6), (36, 26), (36, 42), (38, 62), (58, 14), (60, 34), (58, 54)]
FULL_VIEW = [[0, 0], [105, 0], [105, 68], [0, 68]]


def test_back_line_count_needs_the_whole_width_in_view():
    from app.patterns import count_back_line

    pts = np.array(F343, dtype=np.float32)
    assert count_back_line(pts, np.array(FULL_VIEW, np.float32)) == 3
    half = np.array([[0, 0], [105, 0], [105, 30], [0, 30]], np.float32)  # só metade da largura na imagem
    assert count_back_line(pts, half) is None
    assert count_back_line(pts, None) is None
    # Dois jogadores colados lá atrás não são a linha toda.
    huddle = np.array([(20, 30), (21, 34), (40, 10), (40, 30), (42, 50), (60, 34)], np.float32)
    assert count_back_line(huddle, np.array(FULL_VIEW, np.float32)) is None


def test_back_count_and_manual_choice_decide_the_formation():
    from app.patterns import parse_formation

    xs = np.array([22, 20, 20, 22, 40, 38, 38, 40, 60, 60], dtype=np.float32)  # dados ambíguos
    assert len(split_lines(xs, back=3)[0]) == 3
    assert [len(g) for g in split_lines(xs, sizes=(3, 4, 3))] == [3, 4, 3]
    assert parse_formation("3-4-3") == (3, 4, 3)
    for bad in ("3-4-2", "2-5-3", "x-y", "10"):
        with pytest.raises(ValueError):
            parse_formation(bad)


def test_store_counts_the_back_line_and_respects_overrides():
    store = PatternStore()
    rng = np.random.default_rng(5)
    for i in range(200):
        players = [{"x": 3.0, "y": 34.0, "t": 0, "l": "goleiro", "g": False, "age": 0},
                   {"x": 102.0, "y": 34.0, "t": 1, "l": "goleiro", "g": False, "age": 0}]
        for x, y in F343:  # time 0 defende a esquerda num 3-4-3
            players.append({"x": x + rng.normal(0, 1), "y": y + rng.normal(0, 1), "t": 0, "l": "jogador", "g": False, "age": 0})
        for x, y in mirrored(F442):
            players.append({"x": x + rng.normal(0, 1), "y": y + rng.normal(0, 1), "t": 1, "l": "jogador", "g": False, "age": 0})
        holder = players[-1]  # time 1 com a bola: o time 0 defende
        store.observe({"players": players, "ball": {"x": holder["x"] + 0.5, "y": holder["y"], "e": False}}, i * 0.15, FULL_VIEW)
    summary = store.summary()
    defense = summary["options"]["0-defesa"]
    assert defense["backLine"]["estimate"] == 3
    assert defense["pattern"]["formation"].startswith("3-")
    assert defense["pattern"]["formationSource"] == "linha"
    # O time 1 (4-4-2) também teve a linha contada enquanto atacava: 4 atrás.
    assert summary["options"]["1-ataque"]["backLine"]["estimate"] == 4
    store.set_override(0, "defesa", (5, 3, 2))
    manual = store.summary()["options"]["0-defesa"]
    assert manual["pattern"]["formation"] == "5-3-2" and manual["override"] == "5-3-2"
    assert manual["pattern"]["formationSource"] == "manual"
    store.reset()
    assert store.summary()["options"]["0-defesa"]["override"] == "5-3-2"  # a escolha continua depois de zerar
    assert "3-4-3" in summary["formationOptions"]
    tactics = summary["tactics"]["0"]
    assert tactics["positions"][0].startswith("Defende com 3 atrás")
    assert set(tactics) == {"positions", "buildUp", "plays", "changes"}


def test_restart_clock_forgets_old_possession_but_keeps_samples():
    store = PatternStore()
    store.possession, store.possession_ts, store.last_ts = 0, 5000.0, 5000.0
    store.samples[(0, "ataque")].frames.append(np.zeros((6, 2), np.float32))
    store.restart_clock()
    assert store.possession is None and store.possession_ts is None and store.last_ts is None
    assert len(store.samples[(0, "ataque")].frames) == 1
