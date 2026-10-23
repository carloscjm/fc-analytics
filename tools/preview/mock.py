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
from app.cards import build_cards, font_css
from app.official import _candidate, assign, name_tokens, ordered, parse_summary
from app.report import build_report

FIX = REPO / "backend" / "tests" / "fixtures"
SCOREBOARD = json.loads((FIX / "espn_scoreboard.json").read_text(encoding="utf-8"))
SUMMARY = json.loads((FIX / "espn_summary.json").read_text(encoding="utf-8"))
official_raw: dict | None = None

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

@app.get("/cards.json")
def cards():
    return {"ready": True, "fontCss": font_css(True),
            "cards": build_cards(state["stats"], state["patterns"], state["insights"]["items"], embed_fonts=False)}


def _official_command(msg: dict) -> dict | None:
    """Dados oficiais com as fixtures dos testes (sem internet)."""
    global official_raw
    kind = msg.get("type")
    if kind == "official_search":
        tokens = name_tokens(msg.get("query")) if msg.get("query") else name_tokens(*state["stats"].get("teamNames") or [], "arsenal bayern")
        found = [_candidate(e, tokens) for e in SCOREBOARD["events"]]
        found = sorted((c for c in found if c["match"] >= 0.8), key=lambda c: -c["match"])
        return {"type": "official_candidates", "candidates": found, "error": None if found else "Nenhum jogo encontrado."}
    if kind == "official_confirm":
        official_raw = parse_summary(SUMMARY, msg.get("eventId"))
        official_raw["order"] = assign(official_raw, state["stats"].get("teamNames") or [None, None])
    elif kind == "official_swap" and official_raw:
        official_raw["order"] = official_raw["order"][::-1]
    elif kind == "official_clear":
        official_raw = None
    elif kind == "finish_match":
        state["stats"]["matchState"] = "finalizada"
    else:
        return None
    state["stats"]["official"] = ordered(official_raw)
    return {"type": "stats", "stats": state["stats"]}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "hello", "version": VERSION, "serverTs": 0, "conn": 1})
    await websocket.send_json({**STATUS, "patterns": state["patterns"], "stats": state["stats"], "insights": state["insights"]})
    while True:
        msg = await websocket.receive()
        if msg["type"] == "websocket.disconnect":
            break
        if msg.get("text"):
            reply = _official_command(json.loads(msg["text"]))
            if reply:
                await websocket.send_json(reply)

app.mount("/", StaticFiles(directory=str(REPO / "frontend" / "dist"), html=True), name="web")
