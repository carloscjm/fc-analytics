"""Testes do canal WebSocket com um detector falso (não precisa de GPU nem de modelo)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.protocol import build_frame


from app.detector import Box


@dataclass
class FakeResult:
    boxes: list
    width: int
    height: int
    infer_ms: float


class FakeDetector:
    device_name = "Teste"
    imgsz = 960

    def __init__(self):
        self.model_name = "yolo26s.pt"
        self.seen_shapes = []

    def available_models(self):
        return ["yolo26n.pt", "yolo26s.pt"]

    def ensure_model(self):
        pass

    def set_model(self, name):
        if name not in self.available_models():
            raise ValueError("modelo desconhecido")
        self.model_name = name

    def set_imgsz(self, imgsz):
        if imgsz not in (640, 960, 1280):
            raise ValueError("resolução inválida")
        self.imgsz = imgsz

    def detect(self, image):
        self.seen_shapes.append(image.shape)
        boxes = [Box(10, 20, 30, 60, 0.9, "pessoa"), Box(300, 300, 310, 310, 0.7, "bola")]
        return FakeResult(boxes=boxes, width=image.shape[1], height=image.shape[0], infer_ms=5.0)

    def benchmark(self, frames):
        return {"rows": [{"model": "yolo26n.pt", "meanMs": 5.0, "p95Ms": 6.0, "fps": 200.0}],
                "imgsz": self.imgsz, "budgetMs": 50.0, "frames": len(frames),
                "recommended": "yolo26n.pt", "device": self.device_name}


def jpeg(width=1280, height=720) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((height, width, 3), 80, dtype=np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture
def client():
    app.state.detector = FakeDetector()
    with TestClient(app) as c:
        yield c
    del app.state.detector
    if hasattr(app.state, "pipeline"):
        del app.state.pipeline


def open_ws(client):
    ws = client.websocket_connect("/ws")
    conn = ws.__enter__()
    assert conn.receive_json()["type"] == "hello"
    status = conn.receive_json()
    assert status["type"] == "status"
    return ws, conn, status


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_on_connect(client):
    ws, conn, status = open_ws(client)
    assert status["model"] == "yolo26s.pt"
    assert status["models"] == ["yolo26n.pt", "yolo26s.pt"]
    assert status["device"] == "Teste"
    ws.__exit__(None, None, None)


def test_frame_returns_detections_with_ids(client):
    ws, conn, _ = open_ws(client)
    conn.send_bytes(build_frame(7, 1234.5, jpeg()))
    msg = conn.receive_json()
    assert msg["type"] == "detections"
    assert msg["frameId"] == 7
    assert msg["captureTs"] == 1234.5
    assert (msg["width"], msg["height"]) == (1280, 720)
    ball = [b for b in msg["boxes"] if b["l"] == "bola"]
    assert ball and ball[0]["b"] == [300, 300, 310, 310] and ball[0]["e"] is False
    assert msg["inferMs"] == 5.0
    assert msg["teams"]["state"] == "calibrando"
    assert "active" in msg["tracking"]
    ws.__exit__(None, None, None)


def test_invalid_frame_is_reported(client):
    ws, conn, _ = open_ws(client)
    conn.send_bytes(build_frame(1, 0.0, b"nao-e-jpeg"))
    assert conn.receive_json()["type"] == "error"
    ws.__exit__(None, None, None)


def test_switch_model_and_imgsz(client):
    ws, conn, _ = open_ws(client)
    conn.send_json({"type": "set_model", "name": "yolo26n.pt"})
    assert conn.receive_json()["state"] == "carregando"
    assert conn.receive_json()["model"] == "yolo26n.pt"

    conn.send_json({"type": "set_imgsz", "imgsz": 1280})
    assert conn.receive_json()["imgsz"] == 1280

    conn.send_json({"type": "set_model", "name": "nao-existe.pt"})
    conn.receive_json()
    assert conn.receive_json()["state"] == "erro"
    ws.__exit__(None, None, None)


def test_benchmark_uses_received_frames(client):
    ws, conn, _ = open_ws(client)
    for i in range(3):
        conn.send_bytes(build_frame(i, float(i), jpeg()))
        conn.receive_json()
    conn.send_json({"type": "benchmark"})
    assert conn.receive_json()["state"] == "medindo"
    report = conn.receive_json()
    assert report["type"] == "benchmark"
    assert report["frames"] == 3
    assert report["recommended"] == "yolo26n.pt"
    ws.__exit__(None, None, None)


def test_benchmark_from_another_tab_uses_capture_frames_and_reaches_both(client):
    capture_ws, capture, _ = open_ws(client)
    for i in range(2):
        capture.send_bytes(build_frame(i, float(i), jpeg()))
        capture.receive_json()

    other_ws, other, _ = open_ws(client)
    other.send_json({"type": "benchmark"})

    for conn in (other, capture):
        assert conn.receive_json()["state"] == "medindo"
        report = conn.receive_json()
        assert report["type"] == "benchmark"
        assert report["frames"] == 2
        assert conn.receive_json()["state"] == "pronto"

    other.send_json({"type": "set_model", "name": "yolo26n.pt"})
    for conn in (other, capture):
        assert conn.receive_json()["state"] == "carregando"
        assert conn.receive_json()["model"] == "yolo26n.pt"

    other_ws.__exit__(None, None, None)
    capture_ws.__exit__(None, None, None)


def test_ping_pong(client):
    ws, conn, _ = open_ws(client)
    conn.send_json({"type": "ping", "clientTs": 99})
    pong = conn.receive_json()
    assert pong["type"] == "pong"
    assert pong["clientTs"] == 99
    ws.__exit__(None, None, None)


def test_debug_endpoints_show_last_frame(client):
    assert client.get("/debug/state").json()["frames"] is False
    assert client.get("/debug/snapshot.jpg").status_code == 404
    ws, conn, _ = open_ws(client)
    conn.send_bytes(build_frame(1, 1000.0, jpeg()))
    conn.receive_json()
    state = client.get("/debug/state").json()
    assert state["frames"] is True and state["teams"]["state"] == "calibrando"
    snap = client.get("/debug/snapshot.jpg")
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
    ws.__exit__(None, None, None)


def test_match_events_are_broadcast(client):
    ws, conn, status = open_ws(client)
    assert status["stats"]["score"] == [0, 0] or "matchId" in status["stats"]
    conn.send_json({"type": "new_match"})
    message = conn.receive_json()
    assert message["type"] == "stats" and message["stats"]["score"] == [0, 0]
    assert conn.receive_json()["type"] == "patterns"
    conn.send_json({"type": "event", "kind": "gol", "team": 1})
    message = conn.receive_json()
    assert message["stats"]["score"] == [0, 1]
    assert message["stats"]["events"][-1]["kind"] == "gol"
    conn.send_json({"type": "event", "kind": "gol"})
    assert conn.receive_json()["type"] == "error"
    conn.send_json({"type": "undo_event"})
    assert conn.receive_json()["stats"]["score"] == [0, 0]
    assert client.get("/debug/stats").json()["ready"] is True
    ws.__exit__(None, None, None)


def test_wipe_data_resets_everything(client):
    ws, conn, status = open_ws(client)
    assert "storageBytes" in status["stats"]
    conn.send_json({"type": "event", "kind": "gol", "team": 0})
    assert conn.receive_json()["stats"]["score"][0] >= 1
    conn.send_json({"type": "wipe_data"})
    kinds = [conn.receive_json() for _ in range(4)]
    assert [m["type"] for m in kinds] == ["stats", "patterns", "insights", "wiped"]
    assert kinds[0]["stats"]["score"] == [0, 0] and kinds[0]["stats"]["events"] == []
    assert kinds[2]["items"] == []
    assert kinds[3]["freedBytes"] >= 0
    ws.__exit__(None, None, None)


def test_set_formation_command(client):
    ws, conn, status = open_ws(client)
    conn.send_json({"type": "set_formation", "team": 0, "phase": "defesa", "formation": "3-4-3"})
    message = conn.receive_json()
    assert message["type"] == "patterns" and message["options"]["0-defesa"]["override"] == "3-4-3"
    conn.send_json({"type": "set_formation", "team": 0, "phase": "defesa", "formation": "3-4-2"})
    assert conn.receive_json()["type"] == "error"
    conn.send_json({"type": "set_formation", "team": 0, "phase": "defesa", "formation": None})
    assert conn.receive_json()["options"]["0-defesa"]["override"] is None
    ws.__exit__(None, None, None)


def test_serves_the_built_page(tmp_path, monkeypatch):
    from fastapi.staticfiles import StaticFiles

    (tmp_path / "index.html").write_text("<!doctype html><title>FC Analytics</title>", encoding="utf-8")
    monkeypatch.setenv("FCA_WEB_DIR", str(tmp_path))
    import app.main as main

    assert main._web_dir() == tmp_path
    test_app = main.FastAPI()
    test_app.mount("/", StaticFiles(directory=str(tmp_path), html=True))
    with TestClient(test_app) as c:
        assert "FC Analytics" in c.get("/").text
