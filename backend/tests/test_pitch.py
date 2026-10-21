"""Testes da Fase 3 com uma câmera sintética: homografia, cortes, closes e mapa."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.detector import Box
from app.fieldmap import FieldMap
from app.pitch import (
    KEYPOINTS_M,
    CutDetector,
    HomographyTracker,
    Keypoints,
    apply_h,
    is_close_up,
    visible_area,
)

W, H = 1280, 720
GRASS = (40, 140, 50)
RED = (40, 40, 200)
BLUE = (200, 80, 30)

# Câmera principal mostrando o meio-campo: pitch (metros) → imagem (pixels).
PITCH_TO_IMAGE = cv2.getPerspectiveTransform(
    np.float32([[30, 0], [75, 0], [80, 68], [25, 68]]),
    np.float32([[200, 250], [1080, 250], [1260, 700], [20, 700]]),
)


def synthetic_keypoints(noise: float = 0.0, outlier: bool = False, seed: int = 0) -> Keypoints:
    rng = np.random.default_rng(seed)
    xy = apply_h(PITCH_TO_IMAGE, KEYPOINTS_M).astype(np.float32)
    xy += rng.normal(0, noise, xy.shape).astype(np.float32) if noise else 0
    inside = (xy[:, 0] > 0) & (xy[:, 0] < W) & (xy[:, 1] > 0) & (xy[:, 1] < H)
    conf = np.where(inside, 0.9, 0.05).astype(np.float32)
    if outlier:
        visible = np.flatnonzero(inside)
        xy[visible[0]] += np.float32([120, -80])
    return Keypoints(xy=xy, conf=conf, infer_ms=5.0)


def test_enough_keypoints_are_visible_in_the_synthetic_view():
    assert synthetic_keypoints().conf.__ge__(0.5).sum() >= 6


@pytest.mark.parametrize("noise,outlier", [(0.0, False), (1.5, False), (1.5, True)])
def test_homography_recovers_positions_in_meters(noise, outlier):
    tracker = HomographyTracker()
    view = tracker.update(synthetic_keypoints(noise, outlier), W, H, ts=0.0)
    assert view is not None and view.fresh
    truth = np.float32([[52.5, 34.0], [40.0, 20.0], [65.0, 55.0], [47.0, 60.0]])
    feet_px = apply_h(PITCH_TO_IMAGE, truth)
    estimate = apply_h(view.h, feet_px)
    assert np.abs(estimate - truth).max() < (0.2 if noise == 0 else 1.0)


def test_mirrored_labels_are_normalized_to_far_side_at_top():
    kp = synthetic_keypoints()
    # Mesmos pixels, mas com rótulos espelhados na largura (como se o modelo usasse y para o outro lado).
    mirror = [0, 5, 4, 3, 2, 1, 0, 0, 8, 0, 0, 0, 0, 16, 15, 14, 13, 20, 19, 18, 17, 21, 23, 22, 29, 28, 27, 26, 25, 24, 30, 31]
    mirror[0], mirror[5] = 5, 0
    mirror[6], mirror[7] = 7, 6
    mirror[9], mirror[10], mirror[11], mirror[12] = 12, 11, 10, 9
    swapped = Keypoints(xy=kp.xy[mirror], conf=kp.conf[mirror], infer_ms=0)
    view = HomographyTracker().update(swapped, W, H, ts=0.0)
    assert view is not None
    top, bottom = apply_h(view.h, np.float32([[640, 300], [640, 690]]))
    assert top[1] < bottom[1]


def test_points_on_a_single_line_are_rejected():
    kp = synthetic_keypoints()
    only_halfway = np.zeros(32, np.float32)
    only_halfway[[13, 14, 15, 16]] = 0.9  # pontos 14 a 17, todos na linha do meio
    view = HomographyTracker().update(Keypoints(kp.xy, only_halfway, 0), W, H, ts=0.0)
    assert view is None


def test_last_view_is_kept_briefly_then_dropped():
    tracker = HomographyTracker()
    assert tracker.update(synthetic_keypoints(), W, H, ts=0.0) is not None
    empty = Keypoints(np.zeros((32, 2), np.float32), np.zeros(32, np.float32), 0)
    kept = tracker.update(empty, W, H, ts=0.3)
    assert kept is not None and not kept.fresh
    assert tracker.update(empty, W, H, ts=1.5) is None


def test_visible_area_covers_the_middle_of_the_pitch():
    view = HomographyTracker().update(synthetic_keypoints(), W, H, ts=0.0)
    area = visible_area(view.h, W, H)
    assert area is not None and len(area) == 4
    xs = [p[0] for p in area]
    assert min(xs) < 52.5 < max(xs)


def test_cut_detector():
    cuts = CutDetector()
    pitch = np.full((H, W, 3), GRASS, np.uint8)
    crowd = np.random.default_rng(0).integers(0, 255, (H, W, 3), dtype=np.uint8)
    assert cuts.update(pitch) is False
    assert cuts.update(pitch) is False
    assert cuts.update(crowd) is True
    assert cuts.update(crowd) is False


def test_close_up_detection():
    assert is_close_up([Box(100, 50, 300, 600, 0.9, "pessoa")], H)
    assert not is_close_up([Box(100, 300, 120, 360, 0.9, "pessoa")], H)


def test_field_map_ghosts():
    fmap = FieldMap()
    h = np.linalg.inv(PITCH_TO_IMAGE)

    def box_at(tid, x, y, team):
        fx, fy = apply_h(PITCH_TO_IMAGE, np.float32([[x, y]]))[0]
        return {"b": [int(fx - 6), int(fy - 30), int(fx + 6), int(fy)], "l": "jogador", "id": tid, "t": team}

    fmap.update(h, [box_at(1, 50, 30, 0), box_at(2, 60, 40, 1)], ts=0.0, scene="ao vivo")
    snap = fmap.snapshot(0.0)
    assert {p["id"] for p in snap["players"]} == {1, 2}
    p1 = next(p for p in snap["players"] if p["id"] == 1)
    assert abs(p1["x"] - 50) < 0.5 and abs(p1["y"] - 30) < 0.5

    # Os dois ficam visíveis por mais de 1 s.
    fmap.update(h, [box_at(1, 50, 30, 0), box_at(2, 60, 40, 1)], ts=1.2, scene="ao vivo")

    # O jogador 2 sai da imagem: fica como fantasma.
    fmap.update(h, [box_at(1, 50, 30, 0)], ts=2.0, scene="ao vivo")
    ghosts = [p for p in fmap.snapshot(2.0)["players"] if p["g"]]
    assert [g["id"] for g in ghosts] == [2]

    # Um ID novo aparece perto: é o mesmo jogador, o fantasma some.
    fmap.update(h, [box_at(1, 50, 30, 0), box_at(7, 62, 41, 1)], ts=2.5, scene="ao vivo")
    assert not [p for p in fmap.snapshot(2.5)["players"] if p["g"]]

    # Um ID que durou pouco não vira fantasma.
    fmap.update(h, [box_at(1, 50, 30, 0), box_at(7, 62, 41, 1), box_at(9, 20, 10, 0)], ts=2.6, scene="ao vivo")
    fmap.update(h, [box_at(1, 50, 30, 0), box_at(7, 62, 41, 1)], ts=2.7, scene="ao vivo")
    assert 9 not in {p["id"] for p in fmap.snapshot(2.7)["players"]}

    # Sem campo: o mapa pausa e mantém as posições.
    fmap.update(None, [], ts=3.0, scene="close")
    snap = fmap.snapshot(3.0)
    assert snap["scene"] == "close" and snap["players"]


pytest.importorskip("trackers")
from app.pipeline import Pipeline  # noqa: E402


def broadcast_frame(players, shift_px: float = 0.0):
    image = np.full((H, W, 3), GRASS, np.uint8)
    boxes = []
    for x, y, color in players:
        fx, fy = apply_h(PITCH_TO_IMAGE, np.float32([[x, y]]))[0]
        fx += shift_px
        x1, y1, x2, y2 = int(fx - 8), int(fy - 40), int(fx + 8), int(fy)
        image[max(0, y1) : y2, max(0, x1) : x2] = color
        boxes.append(Box(x1, y1, x2, y2, 0.8, "pessoa"))
    return image, boxes


def test_pipeline_puts_players_on_the_map_and_pauses_on_close_up():
    pipe = Pipeline()
    players = [(35 + i * 4, 15 + (i % 4) * 12, RED if i % 2 else BLUE) for i in range(12)]
    out = None
    for step in range(12):
        image, boxes = broadcast_frame(players)
        out = pipe.process(image, boxes, ts=step * 0.15, keypoints=synthetic_keypoints(seed=step, noise=1.0))
    field = out["map"]
    assert field["scene"] == "ao vivo"
    seen = [p for p in field["players"] if not p["g"]]
    assert len(seen) >= 10
    truth = np.array([(x, y) for x, y, _ in players])
    for p in seen:
        assert np.min(np.hypot(truth[:, 0] - p["x"], truth[:, 1] - p["y"])) < 1.5
    assert field["view"] is not None and field["hInv"] is not None

    close = np.full((H, W, 3), GRASS, np.uint8)
    close[100:700, 400:700] = RED
    out = pipe.process(close, [Box(400, 100, 700, 700, 0.9, "pessoa")], ts=2.0, keypoints=synthetic_keypoints())
    assert out["map"]["scene"] == "close"
    assert out["map"]["players"]  # posições anteriores continuam no mapa


def test_pipeline_without_pitch_model_reports_it():
    pipe = Pipeline()
    image, boxes = broadcast_frame([(50, 30, RED)])
    out = pipe.process(image, boxes, ts=0.0, keypoints=None)
    assert out["map"]["scene"] == "sem modelo do campo"


def test_inconsistent_keypoints_are_rejected():
    kp = synthetic_keypoints()
    visible = np.flatnonzero(kp.conf >= 0.5)
    xy = kp.xy.copy()
    # Dois pontos com rótulos trocados: sobram só 4 que concordam entre si.
    xy[visible[0]], xy[visible[-1]] = kp.xy[visible[-1]].copy(), kp.xy[visible[0]].copy()
    assert HomographyTracker().update(Keypoints(xy, kp.conf, 0), W, H, ts=0.0) is None
