"""Backend do FC Analytics.

Fase 1: recebe frames JPEG da aba capturada, roda a detecção com YOLO e
devolve as caixas. Também troca de modelo e mede o desempenho de cada tamanho.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Protocol

import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .protocol import FrameFormatError, parse_frame

VERSION = "0.1.0"
log = logging.getLogger("fc-analytics")


class DetectorLike(Protocol):
    device_name: str
    imgsz: int

    @property
    def model_name(self) -> str | None: ...
    def available_models(self) -> list[str]: ...
    def ensure_model(self) -> None: ...
    def set_model(self, name: str) -> None: ...
    def set_imgsz(self, imgsz: int) -> None: ...
    def detect(self, image: np.ndarray) -> Any: ...
    def benchmark(self, frames: list[np.ndarray]) -> dict[str, Any]: ...


def create_detector() -> DetectorLike:
    from .detector import Detector

    return Detector()


def decode(jpeg: bytes) -> np.ndarray:
    from .detector import decode_jpeg

    return decode_jpeg(jpeg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "detector"):
        app.state.detector = create_detector()
    app.state.model_ready = asyncio.Event()
    # Compartilhados entre conexões: a medição disparada de qualquer aba usa os
    # frames reais da captura, e mudanças de modelo aparecem em todas as abas.
    app.state.recent_frames = deque(maxlen=20)
    app.state.clients = set()

    async def warm() -> None:
        try:
            await asyncio.to_thread(app.state.detector.ensure_model)
        except Exception:  # noqa: BLE001
            log.exception("falha ao carregar o modelo padrão")
        finally:
            app.state.model_ready.set()

    task = asyncio.create_task(warm())
    yield
    task.cancel()


app = FastAPI(title="FC Analytics", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_ms() -> float:
    return time.time() * 1000


async def send(websocket: WebSocket, message: dict[str, Any]) -> None:
    """Envia JSON com uma trava por conexão, para envios de tarefas diferentes não se misturarem."""
    lock = websocket.scope.setdefault("fca_send_lock", asyncio.Lock())
    async with lock:
        await websocket.send_json(message)


async def broadcast(app: FastAPI, message: dict[str, Any]) -> None:
    for client in list(app.state.clients):
        try:
            await send(client, message)
        except Exception:  # noqa: BLE001 - conexão já fechada
            app.state.clients.discard(client)


def status_message(detector: DetectorLike, state: str = "pronto", detail: str | None = None) -> dict[str, Any]:
    from .detector import IMGSZ_OPTIONS

    return {
        "type": "status",
        "state": state,
        "detail": detail,
        "model": detector.model_name,
        "models": detector.available_models(),
        "imgsz": detector.imgsz,
        "imgszOptions": IMGSZ_OPTIONS,
        "device": detector.device_name,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    detector: DetectorLike = websocket.app.state.detector
    await websocket.accept()
    await send(websocket, {"type": "hello", "version": VERSION, "serverTs": now_ms()})

    ready: asyncio.Event = websocket.app.state.model_ready
    if not ready.is_set():
        await send(websocket, status_message(detector, "carregando", "Carregando o modelo de detecção..."))
        await ready.wait()
    await send(websocket, status_message(detector))

    recent_frames: deque[np.ndarray] = websocket.app.state.recent_frames
    websocket.app.state.clients.add(websocket)
    try:
        await _serve(websocket, detector, recent_frames)
    finally:
        websocket.app.state.clients.discard(websocket)


async def _serve(websocket: WebSocket, detector: DetectorLike, recent_frames: deque[np.ndarray]) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            break

        if message.get("bytes") is not None:
            await handle_frame(websocket, detector, message["bytes"], recent_frames)
            continue

        text = message.get("text")
        if text is None:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            await send(websocket, {"type": "error", "detail": "JSON inválido"})
            continue

        await handle_command(websocket, detector, data, recent_frames)


async def handle_frame(
    websocket: WebSocket, detector: DetectorLike, raw: bytes, recent_frames: deque[np.ndarray]
) -> None:
    received = time.perf_counter()
    try:
        packet = parse_frame(raw)
        image = await asyncio.to_thread(decode, packet.jpeg)
    except (FrameFormatError, ValueError) as exc:
        await send(websocket, {"type": "error", "detail": f"frame inválido: {exc}"})
        return
    decode_ms = (time.perf_counter() - received) * 1000
    recent_frames.append(image)

    try:
        result = await asyncio.to_thread(detector.detect, image)
    except Exception as exc:  # noqa: BLE001
        log.exception("falha na detecção")
        await send(
            websocket,
            {"type": "detections", "frameId": packet.frame_id, "captureTs": packet.capture_ts, "error": str(exc)}
        )
        return

    await send(
        websocket,
        {
            "type": "detections",
            "frameId": packet.frame_id,
            "captureTs": packet.capture_ts,
            "width": result.width,
            "height": result.height,
            "decodeMs": round(decode_ms, 1),
            "inferMs": round(result.infer_ms, 1),
            "serverMs": round((time.perf_counter() - received) * 1000, 1),
            "model": detector.model_name,
            "imgsz": detector.imgsz,
            "boxes": [box.to_json() for box in result.boxes],
        }
    )


async def handle_command(
    websocket: WebSocket, detector: DetectorLike, data: dict[str, Any], recent_frames: deque[np.ndarray]
) -> None:
    kind = data.get("type")

    if kind == "ping":
        await send(websocket, {"type": "pong", "clientTs": data.get("clientTs"), "serverTs": now_ms()})

    elif kind == "set_model":
        name = str(data.get("name"))
        await broadcast(websocket.app, status_message(detector, "carregando", f"Carregando {name}..."))
        try:
            await asyncio.to_thread(detector.set_model, name)
        except Exception as exc:  # noqa: BLE001
            await broadcast(websocket.app, status_message(detector, "erro", f"Não foi possível carregar {name}: {exc}"))
            return
        await broadcast(websocket.app, status_message(detector))

    elif kind == "set_imgsz":
        try:
            detector.set_imgsz(int(data.get("imgsz", 0)))
        except ValueError as exc:
            await broadcast(websocket.app, status_message(detector, "erro", str(exc)))
            return
        await broadcast(websocket.app, status_message(detector))

    elif kind == "benchmark":
        await broadcast(
            websocket.app,
            status_message(detector, "medindo", "Medindo os modelos (na primeira vez, baixa os que faltam)...")
        )
        frames = list(recent_frames)
        try:
            report = await asyncio.to_thread(detector.benchmark, frames)
        except Exception as exc:  # noqa: BLE001
            await broadcast(websocket.app, status_message(detector, "erro", f"Falha na medição: {exc}"))
            return
        await broadcast(websocket.app, {"type": "benchmark", **report})
        await broadcast(websocket.app, status_message(detector))

    else:
        await send(websocket, {"type": "error", "detail": f"tipo desconhecido: {kind!r}"})
