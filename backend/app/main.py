"""Backend do FC Analytics.

Recebe frames JPEG da aba capturada, roda a detecção com YOLO (Fase 1) e o
tracking com separação dos times (Fase 2), e devolve as caixas com ID, time e
papel. Também troca de modelo e mede o desempenho de cada tamanho.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Protocol

import numpy as np
from fastapi import FastAPI, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .protocol import FrameFormatError, parse_frame

FOOTBALL_MODEL = "football-player-detection.pt"

VERSION = "0.5.0"
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


def create_pitch(detector: Any):
    """Detector dos pontos-chave do campo (Fase 3), na mesma GPU do detector de jogadores."""
    from .pitch import PitchDetector

    return PitchDetector(models_dir=detector.models_dir, device=detector.device, half=detector.half)


def create_pipeline():
    from .pipeline import Pipeline

    return Pipeline()


def decode(jpeg: bytes) -> np.ndarray:
    from .detector import decode_jpeg

    return decode_jpeg(jpeg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "detector"):
        app.state.detector = create_detector()
    app.state.setup_warning = None
    if not hasattr(app.state, "pipeline"):
        try:
            app.state.pipeline = create_pipeline()
        except ImportError:
            # Bibliotecas da Fase 2 ainda não instaladas: segue só com a detecção.
            log.exception("tracking indisponível")
            app.state.pipeline = None
            app.state.setup_warning = (
                "Faltam bibliotecas do tracking. Feche as janelas do app, rode o instalar.bat de novo e depois o iniciar.bat."
            )
    if not hasattr(app.state, "pitch"):
        try:
            app.state.pitch = create_pitch(app.state.detector)
        except Exception:  # noqa: BLE001
            log.exception("detector do campo indisponível")
            app.state.pitch = None
    app.state.model_ready = asyncio.Event()
    app.state.next_conn = 0
    # Compartilhados entre conexões: a medição disparada de qualquer aba usa os
    # frames reais da captura, e mudanças de modelo aparecem em todas as abas.
    app.state.recent_frames = deque(maxlen=20)
    app.state.clients = set()
    # Último frame analisado, para a página de diagnóstico (/debug).
    app.state.last_frame = None
    app.state.result_times = deque(maxlen=60)

    async def warm() -> None:
        try:
            await asyncio.to_thread(app.state.detector.ensure_model)
        except Exception:  # noqa: BLE001
            log.exception("falha ao carregar o modelo padrão")
        finally:
            app.state.model_ready.set()
        if app.state.pitch is not None:
            # O modelo do campo é baixado na primeira vez (cerca de 140 MB); a detecção já funciona enquanto isso.
            app.state.pitch.state = "carregando"
            await broadcast(app, status_message(app.state.detector))
            try:
                await asyncio.to_thread(app.state.pitch.ensure)
            except Exception:  # noqa: BLE001
                log.exception("falha ao preparar o modelo do campo")
            await broadcast(app, status_message(app.state.detector))

    task = asyncio.create_task(warm())
    # Nos testes o envio periódico fica desligado, para as mensagens chegarem numa ordem previsível.
    pump = asyncio.create_task(insights_pump(app)) if os.environ.get("FCA_INSIGHTS_PUMP", "1") != "0" else None
    yield
    task.cancel()
    if pump is not None:
        pump.cancel()


app = FastAPI(title="FC Analytics", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def insights_pump(app: FastAPI) -> None:
    """Confere o Ollama e a hora da próxima análise, e manda o feed de insights para as abas quando ele muda."""
    sent = -1
    ticks = 0
    while True:
        await asyncio.sleep(1.0)
        pipeline = getattr(app.state, "pipeline", None)
        if pipeline is None:
            continue
        try:
            if ticks % 5 == 0:
                await asyncio.to_thread(pipeline.insights.tick)
            ticks += 1
            if pipeline.insights.version != sent:
                sent = pipeline.insights.version
                await broadcast(app, {"type": "insights", **pipeline.insights.snapshot()})
        except Exception:  # noqa: BLE001
            log.exception("falha ao enviar os insights")


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

    if detail is None and state == "pronto":
        detail = getattr(app.state, "setup_warning", None)
    return {
        "type": "status",
        "state": state,
        "detail": detail,
        "model": detector.model_name,
        "models": detector.available_models(),
        "imgsz": detector.imgsz,
        "imgszOptions": IMGSZ_OPTIONS,
        "device": detector.device_name,
        "footballModel": FOOTBALL_MODEL in detector.available_models(),
        "pitch": pitch_status(),
    }


def pitch_status() -> dict[str, Any]:
    pitch = getattr(app.state, "pitch", None)
    if pitch is None:
        return {"state": "indisponível", "error": None}
    return {"state": pitch.state, "error": pitch.error}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION}


@app.get("/debug/state")
def debug_state() -> dict:
    """Resumo do último frame analisado: times, tracking, contagens e fps."""
    last = app.state.last_frame
    times = list(app.state.result_times)
    fps = (len(times) - 1) / (times[-1] - times[0]) if len(times) > 1 and times[-1] > times[0] else 0.0
    if last is None:
        return {"frames": False, "fps": 0.0}
    _, message, received = last
    roles: dict[str, int] = {}
    for box in message["boxes"]:
        key = f"time {'AB'[box['t']]}" if box.get("t") in (0, 1) else box["l"]
        roles[key] = roles.get(key, 0) + 1
    return {
        "frames": True,
        "ageS": round(time.time() - received, 1),
        "fps": round(fps, 1),
        "model": message.get("model"),
        "inferMs": message.get("inferMs"),
        "trackMs": message.get("trackMs"),
        "serverMs": message.get("serverMs"),
        "teams": message.get("teams"),
        "tracking": message.get("tracking"),
        "wide": message.get("wide"),
        "pitchMs": message.get("pitchMs"),
        "scene": (message.get("map") or {}).get("scene"),
        "keypoints": (message.get("map") or {}).get("keypoints"),
        "fit": (message.get("map") or {}).get("fit"),
        "frameSize": [message.get("width"), message.get("height")],
        "mapPlayers": len((message.get("map") or {}).get("players") or []),
        "pitch": pitch_status(),
        "roles": roles,
        "ids": sorted(b["id"] for b in message["boxes"] if b.get("id") is not None),
    }


@app.get("/debug/snapshot.jpg")
def debug_snapshot() -> Response:
    """Último frame com as caixas desenhadas na cor de cada time."""
    import cv2

    last = app.state.last_frame
    if last is None:
        return Response(status_code=404)
    image, message, _ = last
    canvas = image.copy()
    teams = message.get("teams") or {}
    colors = teams.get("colors") or ["#f5f5f5", "#3b82f6"]

    def bgr(hex_color: str) -> tuple[int, int, int]:
        n = int(hex_color[1:], 16)
        return (n & 255, (n >> 8) & 255, (n >> 16) & 255)

    role_colors = {"bola": (21, 204, 250), "goleiro": (247, 85, 168), "árbitro": (11, 158, 245),
                   "árbitro/goleiro": (11, 158, 245), "pessoa": (175, 163, 156)}
    for box in message["boxes"]:
        x1, y1, x2, y2 = box["b"]
        color = bgr(colors[box["t"]]) if box.get("t") in (0, 1) else role_colors.get(box["l"], (235, 231, 229))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 0), 4)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        tag = {"bola": "bola", "goleiro": "GOL", "árbitro": "ARB", "árbitro/goleiro": "ARB/GOL"}.get(box["l"], "")
        if box.get("id") is not None:
            tag = f"{tag} {box['id']}".strip()
        if box.get("e"):
            tag = "bola?"
        if tag:
            cv2.putText(canvas, tag, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(canvas, tag, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    field = message.get("map") or {}
    if field.get("hInv"):
        from .pitch import pitch_lines

        h_inv = np.array(field["hInv"], dtype=np.float64).reshape(3, 3)
        for line in pitch_lines():
            pts = np.hstack([line, np.ones((len(line), 1), np.float32)]) @ h_inv.T
            ok_pts = pts[:, 2] > 0
            if ok_pts.sum() < 2:
                continue
            xy = (pts[ok_pts, :2] / pts[ok_pts, 2:3]).round().astype(np.int32)
            cv2.polylines(canvas, [xy], False, (255, 0, 255), 1, cv2.LINE_AA)
    for x, y, idx in field.get("kp") or []:
        cv2.circle(canvas, (int(x), int(y)), 4, (0, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(canvas, str(idx), (int(x) + 5, int(y) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"cena: {field.get('scene')}  pontos: {field.get('keypoints')}", (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(content=buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/debug/stats")
def debug_stats() -> dict:
    pipeline = getattr(app.state, "pipeline", None)
    if pipeline is None:
        return {"ready": False}
    return {"ready": True, **pipeline.latest_stats()}


@app.get("/debug/names")
def debug_names() -> dict:
    pipeline = getattr(app.state, "pipeline", None)
    if pipeline is None:
        return {"ready": False}
    return {
        "ready": True,
        "labels": pipeline.team_labels(),
        "stored": pipeline.team_names.to_json(),
        "colors": pipeline.teams.info().get("colors"),
        "reader": pipeline.name_reader.status(),
    }


@app.get("/debug/insights")
def debug_insights() -> dict:
    pipeline = getattr(app.state, "pipeline", None)
    return {"ready": False} if pipeline is None else {"ready": True, **pipeline.insights.snapshot()}


@app.get("/debug/patterns")
def debug_patterns() -> dict:
    pipeline = getattr(app.state, "pipeline", None)
    latest = pipeline.latest_patterns() if pipeline is not None else None
    if not latest:
        return {"ready": False}
    return {
        "ready": True,
        "team0DefendsLeft": latest.get("team0DefendsLeft"),
        "phaseSource": latest.get("phaseSource"),
        "options": {
            key: {
                "frames": o["frames"],
                "seconds": o["seconds"],
                "formation": (o["pattern"] or {}).get("formation"),
                "lineHeight": (o["pattern"] or {}).get("lineHeight"),
                "width": (o["pattern"] or {}).get("width"),
                "corridors": (o["pattern"] or {}).get("corridors"),
            }
            for key, o in latest["options"].items()
        },
    }


@app.get("/debug/map.png")
def debug_map() -> Response:
    """O mapa visto de cima desenhado em 2D (10 px por metro)."""
    import cv2

    from .pitch import LENGTH, WIDTH, pitch_lines

    last = app.state.last_frame
    scale, pad = 10, 30
    canvas = np.full((int(WIDTH * scale) + 2 * pad, int(LENGTH * scale) + 2 * pad, 3), (40, 110, 45), np.uint8)

    def px(x: float, y: float) -> tuple[int, int]:
        return int(round(pad + x * scale)), int(round(pad + y * scale))

    for line in pitch_lines():
        cv2.polylines(canvas, [np.array([px(x, y) for x, y in line], np.int32)], False, (235, 235, 235), 2, cv2.LINE_AA)
    if last is not None:
        message = last[1]
        field = message.get("map") or {}
        teams = message.get("teams") or {}
        colors = teams.get("colors") or ["#f5f5f5", "#3b82f6"]

        def bgr(hex_color: str) -> tuple[int, int, int]:
            n = int(hex_color[1:], 16)
            return (n & 255, (n >> 8) & 255, (n >> 16) & 255)

        if field.get("view"):
            overlay = canvas.copy()
            cv2.fillPoly(overlay, [np.array([px(x, y) for x, y in field["view"]], np.int32)], (255, 255, 255))
            canvas = cv2.addWeighted(overlay, 0.15, canvas, 0.85, 0)
        for player in field.get("players") or []:
            if player["t"] in (0, 1):
                color = bgr(colors[player["t"]])
            else:
                color = (11, 158, 245) if "árbitro" in player["l"] else (247, 85, 168)
            center = px(player["x"], player["y"])
            if player["g"]:
                cv2.circle(canvas, center, 8, color, 1, cv2.LINE_AA)
            else:
                cv2.circle(canvas, center, 8, color, -1, cv2.LINE_AA)
                cv2.circle(canvas, center, 8, (0, 0, 0), 1, cv2.LINE_AA)
        trail = field.get("trail") or []
        if len(trail) > 1:
            cv2.polylines(canvas, [np.array([px(x, y) for x, y in trail], np.int32)], False, (21, 204, 250), 1, cv2.LINE_AA)
        if field.get("ball"):
            cv2.circle(canvas, px(field["ball"]["x"], field["ball"]["y"]), 5, (21, 204, 250), -1, cv2.LINE_AA)
        cv2.putText(canvas, f"cena: {field.get('scene')}", (pad, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    ok, buf = cv2.imencode(".png", canvas)
    return Response(content=buf.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    detector: DetectorLike = websocket.app.state.detector
    await websocket.accept()
    conn = websocket.app.state.next_conn = websocket.app.state.next_conn + 1
    websocket.scope["fca_conn"] = conn
    await send(websocket, {"type": "hello", "version": VERSION, "serverTs": now_ms(), "conn": conn})

    ready: asyncio.Event = websocket.app.state.model_ready
    if not ready.is_set():
        await send(websocket, status_message(detector, "carregando", "Carregando o modelo de detecção..."))
        await ready.wait()
    # Quem chega agora (uma aba nova) já recebe os padrões acumulados junto com o status.
    pipeline = websocket.app.state.pipeline
    first_status = status_message(detector)
    if pipeline is not None and pipeline.latest_patterns() is not None:
        first_status["patterns"] = pipeline.latest_patterns()
    if pipeline is not None:
        first_status["stats"] = await asyncio.to_thread(pipeline.latest_stats)
        first_status["insights"] = pipeline.insights.snapshot()
    await send(websocket, first_status)

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

    pipeline = websocket.app.state.pipeline
    pitch = websocket.app.state.pitch

    def analyse():
        detected = detector.detect(image)
        keypoints = pitch.detect(image) if pitch is not None and pitch.model is not None else None
        return detected, keypoints

    try:
        result, keypoints = await asyncio.to_thread(analyse)
        if pipeline is not None:
            tracked = await asyncio.to_thread(
                pipeline.process, image, result.boxes, packet.capture_ts / 1000, keypoints
            )
        else:
            tracked = {"boxes": [b.to_json() for b in result.boxes], "teams": None, "tracking": None, "trackMs": None}
    except Exception as exc:  # noqa: BLE001
        log.exception("falha na detecção")
        await send(
            websocket,
            {"type": "detections", "frameId": packet.frame_id, "captureTs": packet.capture_ts, "error": str(exc)}
        )
        return

    message = {
            "type": "detections",
            "frameId": packet.frame_id,
            "captureTs": packet.capture_ts,
            "width": result.width,
            "height": result.height,
            "decodeMs": round(decode_ms, 1),
            "inferMs": round(result.infer_ms, 1),
            "pitchMs": round(keypoints.infer_ms, 1) if keypoints is not None else None,
            "conn": websocket.scope.get("fca_conn"),
            "serverMs": round((time.perf_counter() - received) * 1000, 1),
            "trackMs": tracked["trackMs"],
            "model": detector.model_name,
            "imgsz": detector.imgsz,
            "boxes": tracked["boxes"],
            "teams": tracked["teams"],
            "tracking": tracked["tracking"],
            "wide": tracked.get("wide"),
            "map": tracked.get("map"),
            "patterns": tracked.get("patterns"),
            "stats": tracked.get("stats"),
        }
    websocket.app.state.last_frame = (image, message, time.time())
    websocket.app.state.result_times.append(time.time())
    # Todas as abas abertas recebem o resultado: dá para ver o mapa numa segunda janela.
    await broadcast(websocket.app, message)


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

    elif kind == "reset_session":
        # A página começou uma captura nova: tracking, times e bola recomeçam.
        if websocket.app.state.pipeline is not None:
            websocket.app.state.pipeline.reset()

    elif kind == "reset_patterns":
        if websocket.app.state.pipeline is not None:
            websocket.app.state.pipeline.reset_patterns()
            await broadcast(websocket.app, {"type": "patterns", **websocket.app.state.pipeline.latest_patterns()})

    elif kind in ("event", "undo_event", "new_match"):
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            await send(websocket, {"type": "error", "detail": "As estatísticas precisam das bibliotecas do tracking."})
            return
        try:
            if kind == "event":
                team = data.get("team")
                pipeline.stats.add_event(str(data.get("kind")), int(team) if team is not None else None)
            elif kind == "undo_event":
                pipeline.stats.undo_event()
            else:
                await asyncio.to_thread(pipeline.new_match)
        except ValueError as exc:
            await send(websocket, {"type": "error", "detail": str(exc)})
            return
        stats = await asyncio.to_thread(pipeline.refresh_stats)
        pipeline.stats_sent = pipeline.stats_version
        await broadcast(websocket.app, {"type": "stats", "stats": stats})
        if kind == "new_match":
            await broadcast(websocket.app, {"type": "patterns", **pipeline.latest_patterns()})

    elif kind == "set_formation":
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            return
        try:
            await asyncio.to_thread(
                pipeline.set_formation, int(data.get("team", -1)), str(data.get("phase", "")), data.get("formation") or None
            )
        except (TypeError, ValueError) as exc:
            await send(websocket, {"type": "error", "detail": str(exc)})
            return
        await broadcast(websocket.app, {"type": "patterns", **pipeline.latest_patterns()})

    elif kind == "wipe_data":
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            return
        freed = await asyncio.to_thread(pipeline.wipe_all)
        pipeline.stats_sent = pipeline.stats_version
        await broadcast(websocket.app, {"type": "stats", "stats": pipeline.latest_stats()})
        await broadcast(websocket.app, {"type": "patterns", **pipeline.latest_patterns()})
        await broadcast(websocket.app, {"type": "insights", **pipeline.insights.snapshot()})
        await broadcast(websocket.app, {"type": "wiped", "freedBytes": freed})

    elif kind in ("set_team_names", "swap_team_names", "auto_team_names"):
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            return
        try:
            if kind == "set_team_names":
                pipeline.set_team_names(data.get("names"))
            elif kind == "swap_team_names":
                pipeline.swap_team_names()
            else:
                pipeline.auto_team_names()
        except ValueError as exc:
            await send(websocket, {"type": "error", "detail": str(exc)})
            return
        stats = await asyncio.to_thread(pipeline.refresh_stats)
        pipeline.stats_sent = pipeline.stats_version
        await broadcast(websocket.app, {"type": "stats", "stats": stats})

    elif kind in ("insight_delete", "insights_clear"):
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            return
        if kind == "insight_delete":
            try:
                pipeline.insights.remove(int(data.get("id")))
            except (TypeError, ValueError):
                await send(websocket, {"type": "error", "detail": "item inválido"})
                return
        else:
            pipeline.insights.clear()
        await broadcast(websocket.app, {"type": "insights", **pipeline.insights.snapshot()})

    elif kind in ("llm_analyze_now", "llm_set_model", "llm_pull", "llm_set_interval"):
        pipeline = websocket.app.state.pipeline
        if pipeline is None:
            await send(websocket, {"type": "error", "detail": "Os insights precisam das bibliotecas do tracking."})
            return
        engine = pipeline.insights
        try:
            if kind == "llm_analyze_now":
                if engine.latest_stats is None:
                    await asyncio.to_thread(pipeline.refresh_stats)
                if not engine.analyze_now():
                    await send(websocket, {"type": "error", "detail": engine.llm.last_error or "O LLM está ocupado."})
            elif kind == "llm_set_model":
                engine.set_model(str(data.get("model") or ""))
            elif kind == "llm_pull":
                engine.pull(str(data.get("model") or "") or None)
            else:
                engine.set_interval(int(data.get("seconds", 0)))
        except ValueError as exc:
            await send(websocket, {"type": "error", "detail": str(exc)})

    elif kind == "recalibrate_teams":
        if websocket.app.state.pipeline is not None:
            websocket.app.state.pipeline.recalibrate_teams()

    elif kind == "download_football_model":
        await broadcast(
            websocket.app,
            status_message(detector, "carregando", "Baixando o modelo de futebol (cerca de 130 MB)..."),
        )
        try:
            await asyncio.to_thread(detector.download_football_model)
            await asyncio.to_thread(detector.set_model, FOOTBALL_MODEL)
            if websocket.app.state.pipeline is not None:
                websocket.app.state.pipeline.reset()
        except Exception as exc:  # noqa: BLE001
            await broadcast(websocket.app, status_message(detector, "erro", f"Falha ao baixar o modelo: {exc}"))
            return
        await broadcast(websocket.app, status_message(detector))

    else:
        await send(websocket, {"type": "error", "detail": f"tipo desconhecido: {kind!r}"})
