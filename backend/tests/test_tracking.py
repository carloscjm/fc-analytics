"""Testes do tracking, da separação dos times e da bola com imagens sintéticas."""

from __future__ import annotations

import numpy as np
import pytest

from app.ball import BallTracker
from app.detector import Box
from app.teams import OUTLIER, TeamClassifier, jersey_feature

pytest.importorskip("trackers")
from app.pipeline import Pipeline  # noqa: E402

GRASS = (40, 140, 50)  # BGR
RED = (40, 40, 200)
BLUE = (200, 80, 30)
BLACK = (20, 20, 20)


def pitch_with_players(players: list[tuple[int, int, tuple[int, int, int]]], shift: int = 0) -> tuple[np.ndarray, list[Box]]:
    image = np.full((720, 1280, 3), GRASS, dtype=np.uint8)
    boxes = []
    for x, y, color in players:
        x += shift
        image[y : y + 80, x : x + 30] = color
        boxes.append(Box(x, y, x + 30, y + 80, 0.9, "pessoa"))
    return image, boxes


def team_layout() -> list[tuple[int, int, tuple[int, int, int]]]:
    players = []
    for i in range(8):
        players.append((60 + i * 140, 120, RED))
        players.append((60 + i * 140, 420, BLUE))
    players.append((640, 600, BLACK))
    return players


def test_jersey_feature_ignores_grass():
    image, boxes = pitch_with_players([(100, 100, RED)])
    b = boxes[0]
    wide = (b.x1 - 20, b.y1, b.x2 + 20, b.y2)  # caixa com gramado dos lados
    f_tight = jersey_feature(image, (b.x1, b.y1, b.x2, b.y2))
    f_wide = jersey_feature(image, wide)
    assert f_tight is not None and f_wide is not None
    assert np.linalg.norm(f_tight - f_wide) < 5


def test_team_classifier_splits_colors_and_flags_referee():
    clf = TeamClassifier()
    image, boxes = pitch_with_players(team_layout())
    for step in range(4):
        for tid, b in enumerate(boxes):
            clf.observe(tid, jersey_feature(image, (b.x1, b.y1, b.x2, b.y2)), ts=step * 0.15)
    assert clf.ready
    reds = {clf.team_of(t) for t in range(0, 16, 2)}
    blues = {clf.team_of(t) for t in range(1, 16, 2)}
    assert len(reds) == 1 and len(blues) == 1 and reds != blues
    assert OUTLIER not in reds | blues
    assert clf.team_of(16) == OUTLIER
    assert len(clf.info()["colors"]) == 2


def test_ball_is_estimated_briefly_then_dropped():
    ball = BallTracker()
    assert ball.update([((100, 100, 110, 110), 0.8)], 0.0).estimated is False
    assert ball.update([((120, 100, 130, 110), 0.8)], 0.2).estimated is False
    guess = ball.update([], 0.4)
    assert guess is not None and guess.estimated and guess.box[0] > 120
    assert ball.update([], 1.5) is None


def test_pipeline_keeps_ids_and_assigns_teams_while_camera_pans():
    pipe = Pipeline()
    ids_by_frame = []
    out = None
    for step in range(12):
        image, boxes = pitch_with_players(team_layout(), shift=step * 4)
        out = pipe.process(image, boxes, ts=step * 0.15)
        ids_by_frame.append({b["id"] for b in out["boxes"] if b["id"] is not None})
    stable = ids_by_frame[3]
    assert len(stable) == 17
    assert all(ids == stable for ids in ids_by_frame[3:])

    assert out["teams"]["state"] == "pronto"
    teams = [b["t"] for b in out["boxes"] if b["l"] == "jogador"]
    assert teams.count(0) == 8 and teams.count(1) == 8
    assert sum(1 for b in out["boxes"] if b["l"] == "árbitro/goleiro") == 1


def test_pipeline_resets_when_clock_goes_back():
    pipe = Pipeline()
    image, boxes = pitch_with_players(team_layout())
    for step in range(3):
        pipe.process(image, boxes, ts=10 + step * 0.15)
    out = pipe.process(image, boxes, ts=1.0)  # página recarregada
    assert out["tracking"]["active"] == 0 or out["teams"]["state"] == "calibrando"
