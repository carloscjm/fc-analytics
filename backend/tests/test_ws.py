from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ws_ping_pong_and_frame_ack():
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        ws.send_json({"type": "ping", "clientTs": 123})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert pong["clientTs"] == 123

        ws.send_bytes(b"\xff\xd8fake-jpeg")
        ack = ws.receive_json()
        assert ack["type"] == "frame_ack"
        assert ack["bytes"] == 11


def test_ws_rejects_invalid_json():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("isso não é json")
        assert ws.receive_json()["type"] == "error"
