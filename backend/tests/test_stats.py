"""Testes das estatísticas da partida (Fase 4) com jogadas sintéticas."""

from __future__ import annotations

import pytest

from app.stats import MatchStore, StatsTracker, corridor_of, shape_of

import numpy as np

# Time 0 defende o gol da esquerda (x = 0); time 1, o da direita.
TEAM0 = [(30, 10), (28, 26), (28, 42), (30, 58), (50, 12), (48, 28), (48, 40), (50, 56), (68, 28), (68, 40)]
TEAM1 = [(105 - x, 68 - y) for x, y in TEAM0]


def field(ball, t, jog=0.0, extra=None):
    players = []
    for i, (x, y) in enumerate(TEAM0):
        players.append({"id": i + 1, "x": x, "y": y + jog * t, "t": 0, "l": "jogador", "g": False, "age": 0})
    for i, (x, y) in enumerate(TEAM1):
        players.append({"id": i + 101, "x": x, "y": y, "t": 1, "l": "jogador", "g": False, "age": 0})
    for p in extra or []:
        players.append(p)
    return {"players": players, "ball": ball}


def near(team, index, t=0.0, jog=0.0, dx=0.5):
    x, y = (TEAM0 if team == 0 else TEAM1)[index]
    if team == 0:
        y = y + jog * t
    return {"x": x + dx, "y": y, "e": False}


def run(tracker, start, seconds, ball_fn, step=0.15, jog=0.0, extra=None):
    t = 0.0
    while t < seconds:
        tracker.observe(field(ball_fn(t), start + t, jog=jog, extra=extra), True, start + t)
        t += step
    return start + seconds


def test_shape_and_corridor_helpers():
    pts = np.array(TEAM0, dtype=np.float32)
    line, depth, width = shape_of(pts)
    assert 28 <= line <= 30
    assert depth == pytest.approx(40)
    assert width == pytest.approx(48)
    assert shape_of(pts[:4]) is None
    assert [corridor_of(y) for y in (5, 34, 60)] == [0, 1, 2]


def test_pass_loss_pressure_and_possession():
    tracker = StatsTracker(None, now=1000.0)
    now = 1000.0
    # Time 0 com a bola no zagueiro (id 2), depois passa para o meia (id 6).
    now = run(tracker, now, 4, lambda t: near(0, 1))
    now = run(tracker, now, 4, lambda t: near(0, 5))
    # Perde a bola para um jogador do time 1 ao lado do meia, que pressiona na hora.
    thief = {"id": 150, "x": 51.5, "y": 28, "t": 1, "l": "jogador", "g": False, "age": 0}
    now = run(tracker, now, 2, lambda t: {"x": 52.0, "y": 28, "e": False}, extra=[thief])
    # Recupera em 2 s com o meia (id 6) e fica com ela.
    now = run(tracker, now, 8, lambda t: near(0, 5))
    s = tracker.summary(now=now)["windows"]["partida"]
    assert s["passes"][0] == 1
    assert s["losses"][0] == 1
    assert s["losses"][1] == 1  # o time 1 perdeu quando o time 0 recuperou
    assert s["recoveries5s"][0] == 100
    assert s["pressure"][0] is not None and s["pressure"][0] >= 1
    assert s["possession"][0] > 75 and sum(s["possession"]) == pytest.approx(100, abs=0.2)
    assert 28 <= s["line"][0] <= 30
    assert s["passAccuracy"][0] == 50


def test_tilt_corridor_and_distance():
    tracker = StatsTracker(None, now=0.0)
    # Bola com o atacante do time 0 (id 9) no terço ofensivo, pelo lado esquerdo dele (y pequeno).
    attacker = {"id": 50, "x": 80, "y": 8, "t": 0, "l": "jogador", "g": False, "age": 0}
    end = run(tracker, 0.0, 10, lambda t: {"x": 80.5, "y": 8, "e": False}, jog=2.0, extra=[attacker])
    s = tracker.summary(now=end)["windows"]["partida"]
    assert s["tilt"][0] == 100
    assert s["corridors"][0][0] == 100
    assert s["corridors"][1] is None
    # 10 jogadores do time 0 correndo 2 m/s por 10 s: cerca de 200 m.
    assert 0.17 <= s["distanceKm"][0] <= 0.21
    assert s["distanceKm"][1] == 0


def test_recent_window_differs_from_whole_match():
    tracker = StatsTracker(None, now=0.0)
    now = run(tracker, 0.0, 200, lambda t: near(0, 1), step=0.5)
    now = run(tracker, now, 300, lambda t: near(1, 1), step=0.5)
    summary = tracker.summary(now=now)
    whole, recent = summary["windows"]["partida"], summary["windows"]["recentes"]
    assert recent["possession"][1] > 95
    assert 35 < whole["possession"][0] < 45
    assert len(summary["timeline"]["minutes"]) == 9
    assert summary["timeline"]["possession"][0][0] == 100


def test_events_score_and_halftime_pause():
    tracker = StatsTracker(None, now=0.0)
    tracker.add_event("gol", 0, now=60)
    tracker.add_event("amarelo", 1, now=70)
    with pytest.raises(ValueError):
        tracker.add_event("gol", None, now=80)
    with pytest.raises(ValueError):
        tracker.add_event("escanteio", 0, now=80)
    tracker.add_event("intervalo", None, now=90)
    assert tracker.summary(now=95)["paused"] is True
    run(tracker, 95, 5, lambda t: near(0, 1))
    assert tracker.frames == []  # nada é gravado no intervalo
    tracker.add_event("intervalo", None, now=100)
    summary = tracker.summary(now=101)
    assert summary["paused"] is False and summary["period"] == 2
    assert summary["score"] == [1, 0]
    tracker.undo_event()  # desfaz o fim do intervalo
    assert tracker.summary(now=102)["paused"] is True


def test_sqlite_keeps_the_match_after_restart(tmp_path):
    store = MatchStore(tmp_path / "partidas.sqlite")
    tracker = StatsTracker(store, now=1000.0)
    end = run(tracker, 1000.0, 3, lambda t: near(0, 1))
    tracker.add_event("gol", 1, now=end)
    tracker.flush()
    frames = len(tracker.frames)
    match_id = tracker.match_id

    again = StatsTracker(store, now=end + 60)
    assert again.match_id == match_id
    assert len(again.frames) == frames
    assert again.summary(now=end + 60)["score"] == [0, 1]
    with store._lock:
        positions = store._db.execute("SELECT COUNT(*) FROM positions WHERE match_id = ?", (match_id,)).fetchone()[0]
    assert positions == frames * 20

    again.new_match(now=end + 120)
    assert again.match_id != match_id
    assert again.frames == [] and again.summary(now=end + 121)["score"] == [0, 0]

    # Muito tempo depois (outro dia), começa uma partida nova sozinho.
    later = StatsTracker(store, now=end + 10 * 3600)
    assert later.match_id not in (match_id, again.match_id)
