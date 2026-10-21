"""Ciclo da partida (criar, pausar, retomar, finalizar), relatório e padrões refeitos do que foi gravado."""

from __future__ import annotations

from app.patterns import PatternStore
from app.report import build_report, vivid
from app.stats import MatchStore, StatsTracker
from tests.test_stats import near, run


def test_pause_does_not_count_and_finish_stops_recording(tmp_path):
    store = MatchStore(tmp_path / "p.sqlite")
    tracker = StatsTracker(store, now=1000.0)
    tracker.create_match("MCI x PSG", now=1000.0)
    assert tracker.state == "ativa" and tracker.name == "MCI x PSG"
    end = run(tracker, 1000.0, 10.0, lambda t: near(0, 4))
    frames = len(tracker.frames)
    tracker.pause(now=end)
    assert not tracker.recording
    run(tracker, end, 5.0, lambda t: near(0, 4))
    assert len(tracker.frames) == frames  # nada gravado na pausa
    tracker.resume(now=end + 600.0)  # 10 minutos de intervalo
    assert tracker.clock(end + 600.0) == 10.0
    assert tracker.pauses == [[10.0, 600.0]]
    tracker.finish(now=end + 610.0)
    assert tracker.state == "finalizada" and not tracker.recording
    assert tracker.clock(end + 9999.0) == 20.0

    # Depois de reiniciar, a partida volta com o mesmo estado, nome e pausas.
    again = StatsTracker(store, now=end + 700.0)
    assert again.match_id == tracker.match_id
    assert (again.state, again.name, again.pauses) == ("finalizada", "MCI x PSG", [[10.0, 600.0]])
    summary = again.summary(now=end + 700.0)
    assert summary["matchState"] == "finalizada" and summary["elapsedS"] == 20.0


def test_report_is_a_complete_html_page(tmp_path):
    tracker = StatsTracker(MatchStore(tmp_path / "p.sqlite"), now=1000.0)
    tracker.create_match(None, now=1000.0)
    run(tracker, 1000.0, 20.0, lambda t: near(0, 4) if t < 10 else near(1, 4))
    stats = {**tracker.summary(now=1020.0), "teamNames": ["MCI", "PSG"]}
    html = build_report(stats, PatternStore().summary(), [{"kind": "alerta", "t": 65, "team": 0, "text": "Pressão <alta>"}], ["#e05141", "#384f7c"], "0.8.0")
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "MCI x PSG" in html and "Pressão &lt;alta&gt;" in html
    assert "Estatísticas da partida" in html and "<svg" in html


def test_vivid_makes_kit_colors_stronger():
    assert vivid("#e05141", "#000") != "#e05141"
    r, g, b = (int(vivid("#e05141", "#000")[i : i + 2], 16) for i in (1, 3, 5))
    assert r > 200 and g < 70 and b < 70  # vermelho forte
    assert vivid("#eeeeee", "#000") == "#f5f7fa"
    assert vivid(None, "#123456") == "#123456"


def test_replay_rebuilds_patterns_from_saved_positions():
    from app.pipeline import replay_patterns

    import numpy as np

    rng = np.random.default_rng(0)
    base0 = [(25, 10), (22, 26), (22, 42), (25, 58), (45, 10), (42, 28), (42, 40), (45, 58), (65, 28), (65, 40)]
    positions, ball = [], {}
    for i in range(300):
        t = round(i * 0.3, 2)
        for team in (0, 1):
            for j, (x, y) in enumerate(base0):
                x, y = x + rng.normal(0, 1), y + rng.normal(0, 1)
                if team == 1:
                    x, y = 105 - x, 68 - y
                positions.append((t, j + 100 * team, team, "jogador", x, y, 0))
        positions.append((t, 999, 0, "goleiro", 3.0, 34.0, 0))
        ball[t] = (45.5, 10.0)  # com o time 0
    store = PatternStore()
    replay_patterns(store, positions, ball, 1000.0)
    out = store.summary(now=1100.0)
    assert out["options"]["0-ataque"]["frames"] > 200
    assert out["options"]["0-ataque"]["pattern"] is not None
