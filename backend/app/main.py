"""Backend do FC Analytics.

Fase 0: servidor FastAPI com healthcheck e um canal WebSocket que
responde a pings e confirma o recebimento de frames binários.
As etapas de visão computacional entram a partir da Fase 1.
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

VERSION = "0.0.1"

app = FastAPI(title="FC Analytics", version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_ms() -> float:
    return time.time() * 1000


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "hello", "version": VERSION, "serverTs": now_ms()})

    while True:
        message = await websocket.receive()

        if message["type"] == "websocket.disconnect":
            break

        if message.get("bytes") is not None:
            # Fase 1 vai decodificar o JPEG e rodar a detecção aqui.
            await websocket.send_json(
                {"type": "frame_ack", "bytes": len(message["bytes"]), "serverTs": now_ms()}
            )
            continue

        text = message.get("text")
        if text is None:
            continue

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "detail": "JSON inválido"})
            continue

        if data.get("type") == "ping":
            await websocket.send_json(
                {"type": "pong", "clientTs": data.get("clientTs"), "serverTs": now_ms()}
            )
        else:
            await websocket.send_json(
                {"type": "error", "detail": f"tipo desconhecido: {data.get('type')!r}"}
            )
