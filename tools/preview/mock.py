"""Backend falso para fotografar o painel: serve frontend/dist e manda o estado de out/state.json pelo /ws.

Uso (na raiz do repositório, depois do gen.py e do npm run build):
    python -m uvicorn --app-dir tools/preview mock:app --port 8765
Precisa de fastapi, uvicorn e websockets.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend"))
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.report import build_report

VERSION = (REPO / "VERSION").read_text(encoding="utf-8").strip()
state = json.load(open(HERE / "out" / "state.json", encoding="utf-8"))
app = FastAPI()
STATUS = {"type": "status", "state": "pronto", "detail": None, "model": "football-player-detection.pt",
          "models": ["yolo26s.pt", "football-player-detection.pt"], "imgsz": 960, "imgszOptions": [640, 960, 1280],
          "device": "NVIDIA GeForce RTX 4060", "footballModel": True, "pitch": {"state": "pronto", "error": None}}

@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}

@app.get("/report.html")
def report():
    return HTMLResponse(build_report(state["stats"], state["patterns"], state["insights"]["items"], state["stats"]["teamColors"], VERSION))

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "hello", "version": VERSION, "serverTs": 0, "conn": 1})
    await websocket.send_json({**STATUS, "patterns": state["patterns"], "stats": state["stats"], "insights": state["insights"]})
    while True:
        msg = await websocket.receive()
        if msg["type"] == "websocket.disconnect":
            break

app.mount("/", StaticFiles(directory=str(REPO / "frontend" / "dist"), html=True), name="web")
