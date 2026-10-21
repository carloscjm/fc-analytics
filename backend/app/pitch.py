"""Fase 3: encontra o campo na imagem e converte pixels em metros.

- Um modelo de pontos-chave (YOLOv8 pose do projeto roboflow/sports) acha até
  32 pontos do campo: cantos, áreas, meio-campo, círculo central, marcas do pênalti.
- Com 4 ou mais pontos confiáveis, uma homografia (RANSAC) leva cada pixel do
  gramado para metros num campo de 105 x 68 m.
- A homografia é suavizada entre frames e reiniciada nos cortes de câmera.
- Closes, replays e frames sem campo suficiente não produzem homografia: o mapa
  fica pausado na última posição conhecida.

Sistema de coordenadas do campo (metros): x de 0 a 105 ao longo do comprimento
(do gol da esquerda para o da direita, como na câmera principal), y de 0 a 68
na largura (y = 0 é a lateral do lado de lá, no alto da imagem).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

LENGTH = 105.0
WIDTH = 68.0
PENALTY_BOX_WIDTH = 40.32
PENALTY_BOX_LENGTH = 16.5
GOAL_BOX_WIDTH = 18.32
GOAL_BOX_LENGTH = 5.5
CIRCLE_RADIUS = 9.15
PENALTY_SPOT = 11.0


def keypoint_positions() -> np.ndarray:
    """Os 32 pontos na mesma ordem do modelo do roboflow/sports, em metros."""
    L, W = LENGTH, WIDTH
    pbw, pbl, gbw, gbl = PENALTY_BOX_WIDTH, PENALTY_BOX_LENGTH, GOAL_BOX_WIDTH, GOAL_BOX_LENGTH
    r, spot = CIRCLE_RADIUS, PENALTY_SPOT
    return np.array(
        [
            (0, 0),  # 1
            (0, (W - pbw) / 2),  # 2
            (0, (W - gbw) / 2),  # 3
            (0, (W + gbw) / 2),  # 4
            (0, (W + pbw) / 2),  # 5
            (0, W),  # 6
            (gbl, (W - gbw) / 2),  # 7
            (gbl, (W + gbw) / 2),  # 8
            (spot, W / 2),  # 9
            (pbl, (W - pbw) / 2),  # 10
            (pbl, (W - gbw) / 2),  # 11
            (pbl, (W + gbw) / 2),  # 12
            (pbl, (W + pbw) / 2),  # 13
            (L / 2, 0),  # 14
            (L / 2, W / 2 - r),  # 15
            (L / 2, W / 2 + r),  # 16
            (L / 2, W),  # 17
            (L - pbl, (W - pbw) / 2),  # 18
            (L - pbl, (W - gbw) / 2),  # 19
            (L - pbl, (W + gbw) / 2),  # 20
            (L - pbl, (W + pbw) / 2),  # 21
            (L - spot, W / 2),  # 22
            (L - gbl, (W - gbw) / 2),  # 23
            (L - gbl, (W + gbw) / 2),  # 24
            (L, 0),  # 25
            (L, (W - pbw) / 2),  # 26
            (L, (W - gbw) / 2),  # 27
            (L, (W + gbw) / 2),  # 28
            (L, (W + pbw) / 2),  # 29
            (L, W),  # 30
            (L / 2 - r, W / 2),  # 31
            (L / 2 + r, W / 2),  # 32
        ],
        dtype=np.float32,
    )


KEYPOINTS_M = keypoint_positions()


def pitch_lines(samples_per_arc: int = 24) -> list[np.ndarray]:
    """Linhas do campo como polilinhas em metros (para desenhar sobre o vídeo e no diagnóstico)."""
    L, W = LENGTH, WIDTH
    lines: list[list[tuple[float, float]]] = [
        [(0, 0), (L, 0), (L, W), (0, W), (0, 0)],
        [(L / 2, 0), (L / 2, W)],
    ]
    for side in (0, 1):
        def x(v: float) -> float:
            return v if side == 0 else L - v

        top, bottom = (W - PENALTY_BOX_WIDTH) / 2, (W + PENALTY_BOX_WIDTH) / 2
        lines.append([(x(0), top), (x(PENALTY_BOX_LENGTH), top), (x(PENALTY_BOX_LENGTH), bottom), (x(0), bottom)])
        top, bottom = (W - GOAL_BOX_WIDTH) / 2, (W + GOAL_BOX_WIDTH) / 2
        lines.append([(x(0), top), (x(GOAL_BOX_LENGTH), top), (x(GOAL_BOX_LENGTH), bottom), (x(0), bottom)])
        # Meia-lua da área: parte do círculo de 9,15 m em volta da marca do pênalti fora da área.
        cx = x(PENALTY_SPOT)
        half = np.arccos((PENALTY_BOX_LENGTH - PENALTY_SPOT) / CIRCLE_RADIUS)
        angles = np.linspace(-half, half, samples_per_arc)
        sign = 1 if side == 0 else -1
        lines.append([(cx + sign * CIRCLE_RADIUS * np.cos(a), W / 2 + CIRCLE_RADIUS * np.sin(a)) for a in angles])
    angles = np.linspace(0, 2 * np.pi, samples_per_arc * 3)
    lines.append([(L / 2 + CIRCLE_RADIUS * np.cos(a), W / 2 + CIRCLE_RADIUS * np.sin(a)) for a in angles])
    return [np.array(line, dtype=np.float32) for line in lines]


# ---------------------------------------------------------------------------
# Modelo de pontos-chave
# ---------------------------------------------------------------------------

PITCH_MODEL_FILE = "football-pitch-detection.pt"
# Mesmo endereço do examples/soccer/setup.sh do roboflow/sports (licença AGPL-3.0).
PITCH_MODEL_URL = "https://drive.google.com/uc?id=1Ma5Kt86tgpdjCTKfum79YMgNnSjcoOyf"
KEYPOINT_MIN_CONF = 0.5
PITCH_IMGSZ = 640


@dataclass
class Keypoints:
    xy: np.ndarray  # (32, 2) em pixels
    conf: np.ndarray  # (32,)
    infer_ms: float


# Gramado em HSV (OpenCV: matiz 0-180). Pontos do campo ficam sempre sobre a grama ou as linhas brancas.
GRASS_HSV_LOW = np.array([30, 40, 40], dtype=np.uint8)
GRASS_HSV_HIGH = np.array([90, 255, 255], dtype=np.uint8)
GRASS_SCALE = 0.25
GRASS_RADIUS = 0.025  # vizinhança, em fração da largura da imagem
GRASS_MIN_SHARE = 0.25


def keypoints_on_grass(image: np.ndarray, keypoints: Keypoints) -> Keypoints:
    """Zera a confiança dos pontos achados fora do gramado (barras pretas, placar, menus da página).

    O modelo do campo às vezes "acha" pontos em áreas que não são campo, como a
    faixa preta ao lado do vídeo; com eles, o encaixe do campo sai torto e todas
    as posições em metros ficam deslocadas.
    """
    small = cv2.resize(image, None, fx=GRASS_SCALE, fy=GRASS_SCALE, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    grass = cv2.inRange(hsv, GRASS_HSV_LOW, GRASS_HSV_HIGH)
    h, w = grass.shape
    r = max(2, int(GRASS_RADIUS * w))
    conf = keypoints.conf.copy()
    for i, (x, y) in enumerate(keypoints.xy):
        if conf[i] <= 0:
            continue
        cx, cy = int(x * GRASS_SCALE), int(y * GRASS_SCALE)
        if not (0 <= cx < w and 0 <= cy < h):
            conf[i] = 0.0
            continue
        patch = grass[max(0, cy - r) : cy + r + 1, max(0, cx - r) : cx + r + 1]
        if patch.size == 0 or float(np.count_nonzero(patch)) / patch.size < GRASS_MIN_SHARE:
            conf[i] = 0.0
    return Keypoints(xy=keypoints.xy, conf=conf, infer_ms=keypoints.infer_ms)


class PitchDetector:
    def __init__(self, models_dir: Path, device: str, half: bool) -> None:
        self.models_dir = models_dir
        self.device = device
        self.half = half
        self.model: Any = None
        self.state = "ausente"  # ausente | baixando | pronto | erro
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.models_dir / PITCH_MODEL_FILE

    def ensure(self) -> None:
        """Baixa (se preciso) e carrega o modelo. Pode demorar; chame fora do laço principal."""
        with self._lock:
            if self.model is not None:
                return
            try:
                if not self.path.exists():
                    self.state = "baixando"
                    self._download()
                from ultralytics import YOLO

                model = YOLO(str(self.path))
                model.predict(
                    np.zeros((720, 1280, 3), dtype=np.uint8),
                    imgsz=PITCH_IMGSZ,
                    device=self.device,
                    quantize=16 if self.half else None,
                    verbose=False,
                )
                self.model = model
                self.state = "pronto"
                self.error = None
            except Exception as exc:  # noqa: BLE001 - mostrado na página
                self.state = "erro"
                self.error = str(exc)
                raise

    def _download(self) -> None:
        import gdown

        self.models_dir.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".part")
        result = gdown.download(PITCH_MODEL_URL, str(partial), quiet=True)
        if not result or not partial.exists() or partial.stat().st_size < 1_000_000:
            partial.unlink(missing_ok=True)
            raise RuntimeError("o download do modelo do campo não foi concluído")
        partial.replace(self.path)

    def detect(self, image: np.ndarray) -> Keypoints | None:
        if self.model is None:
            return None
        start = time.perf_counter()
        result = self.model.predict(
            image,
            imgsz=PITCH_IMGSZ,
            device=self.device,
            quantize=16 if self.half else None,
            verbose=False,
        )[0]
        infer_ms = (time.perf_counter() - start) * 1000
        kp = result.keypoints
        if kp is None or kp.xy is None or len(kp.xy) == 0 or kp.conf is None:
            return Keypoints(xy=np.zeros((32, 2), np.float32), conf=np.zeros(32, np.float32), infer_ms=infer_ms)
        best = 0
        if result.boxes is not None and len(result.boxes):
            best = int(result.boxes.conf.argmax())
        xy = kp.xy[best].cpu().numpy().astype(np.float32)
        conf = kp.conf[best].cpu().numpy().astype(np.float32)
        return Keypoints(xy=xy, conf=conf, infer_ms=infer_ms)


# ---------------------------------------------------------------------------
# Homografia
# ---------------------------------------------------------------------------

MIN_POINTS = 4
# Com só 4 pontos a homografia sempre "encaixa"; pedir 5 permite checar se os pontos concordam.
MIN_INLIERS = 5
MAX_REPROJECTION = 0.015  # erro médio aceito, em fração da largura da imagem
RANSAC_THRESHOLD_M = 1.5
MIN_SPREAD_M = 8.0
SMOOTHING = 0.5
KEEP_LAST_SECONDS = 1.5
CLOSE_UP_HEIGHT_RATIO = 0.25

# Pontos de controle na imagem (fração da largura/altura) usados para suavizar a homografia.
CONTROL = np.array([[0.1, 0.55], [0.9, 0.55], [0.9, 0.95], [0.1, 0.95], [0.5, 0.75]], dtype=np.float32)


def apply_h(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return points.reshape(0, 2)
    return cv2.perspectiveTransform(points.reshape(-1, 1, 2).astype(np.float32), h).reshape(-1, 2)


# Último motivo de recusa da homografia (aparece no diagnóstico /debug/state).
LAST_FIT: dict[str, object] = {}


def fit_homography(image_xy: np.ndarray, pitch_xy: np.ndarray) -> tuple[np.ndarray | None, int]:
    """Homografia imagem → campo com RANSAC. Retorna (H, inliers)."""
    LAST_FIT.clear()
    LAST_FIT["points"] = int(len(image_xy))
    if len(image_xy) < MIN_POINTS:
        LAST_FIT["reason"] = "poucos pontos"
        return None, 0
    # Pontos alinhados numa reta só (por exemplo, só a linha lateral) não definem o plano.
    spread = np.linalg.svd(pitch_xy - pitch_xy.mean(axis=0), compute_uv=False)
    if spread[-1] < MIN_SPREAD_M / 4 or spread[0] < MIN_SPREAD_M:
        LAST_FIT["reason"] = "pontos alinhados"
        return None, 0
    h, mask = cv2.findHomography(image_xy, pitch_xy, cv2.RANSAC, RANSAC_THRESHOLD_M)
    if h is None or mask is None:
        LAST_FIT["reason"] = "ransac falhou"
        return None, 0
    inliers = int(mask.sum())
    LAST_FIT["inliers"] = inliers
    if inliers < MIN_INLIERS or inliers < 0.5 * len(image_xy):
        # Menos da metade dos pontos concorda: o modelo provavelmente trocou pontos (lado esquerdo e direito, por exemplo).
        LAST_FIT["reason"] = "poucos pontos concordantes"
        return None, inliers
    # Os pontos do campo, levados de volta para a imagem, precisam cair perto de onde o modelo os viu.
    keep = mask.ravel().astype(bool)
    back = apply_h(np.linalg.inv(h), pitch_xy[keep])
    error = float(np.mean(np.linalg.norm(back - image_xy[keep], axis=1)))
    width = float(np.ptp(image_xy[:, 0])) or 1.0
    LAST_FIT["errorPx"] = round(error, 1)
    LAST_FIT["limitPx"] = round(MAX_REPROJECTION * max(width, 640.0), 1)
    if error > MAX_REPROJECTION * max(width, 640.0):
        LAST_FIT["reason"] = "erro de reprojeção alto"
        return None, inliers
    LAST_FIT["reason"] = "ok"
    return h, inliers


FLIP_Y = np.array([[1, 0, 0], [0, -1, WIDTH], [0, 0, 1]], dtype=np.float64)


def _probe(h: np.ndarray, width: int, height: int) -> np.ndarray | None:
    probe = CONTROL * np.array([width, height], dtype=np.float32)
    pts = np.hstack([probe, np.ones((len(probe), 1), np.float32)]) @ h.T
    if np.any(pts[:, 2] <= 0):
        return None
    return pts[:, :2] / pts[:, 2:3]


def orient(h: np.ndarray, width: int, height: int) -> np.ndarray:
    """Deixa a lateral do alto da imagem em y = 0, como quem olha da câmera principal.

    Se o mapa sairia espelhado (ou de cabeça para baixo), inverte a largura do campo.
    """
    xy = _probe(h, width, height)
    if xy is None:
        return h
    a, b, c = xy[0], xy[1], xy[3]
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return FLIP_Y @ h if cross < 0 else h


def plausible(h: np.ndarray, width: int, height: int) -> bool:
    """A metade de baixo da imagem precisa ficar à frente da câmera e perto do campo.

    O centro tem que cair no campo (com folga); os cantos podem cair bem fora
    (atrás do gol, na arquibancada), mas não absurdamente longe.
    """
    xy = _probe(h, width, height)
    if xy is None:
        return False
    center = xy[4]
    if not (-15 < center[0] < LENGTH + 15 and -15 < center[1] < WIDTH + 15):
        return False
    corners = xy[:4]
    inside = (corners[:, 0] > -60) & (corners[:, 0] < LENGTH + 60) & (corners[:, 1] > -60) & (corners[:, 1] < WIDTH + 60)
    return bool(inside.all())


@dataclass
class FieldView:
    h: np.ndarray  # imagem → campo
    h_inv: np.ndarray  # campo → imagem
    points: int
    fresh: bool  # calculada neste frame (False = reaproveitada por um instante)


class HomographyTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.smoothed: np.ndarray | None = None
        self.last: FieldView | None = None
        self.last_ts: float | None = None

    def update(self, keypoints: Keypoints | None, width: int, height: int, ts: float) -> FieldView | None:
        view = self._fit(keypoints, width, height)
        if view is not None:
            self.last, self.last_ts = view, ts
            return view
        if self.last is not None and self.last_ts is not None and ts - self.last_ts <= KEEP_LAST_SECONDS:
            return FieldView(h=self.last.h, h_inv=self.last.h_inv, points=0, fresh=False)
        self.smoothed = None
        return None

    def _fit(self, keypoints: Keypoints | None, width: int, height: int) -> FieldView | None:
        if keypoints is None:
            return None
        # Pontos colados na borda costumam ser chutes do modelo para fora da imagem.
        mx, my = 0.01 * width, 0.01 * height
        good = (
            (keypoints.conf >= KEYPOINT_MIN_CONF)
            & (keypoints.xy[:, 0] > mx)
            & (keypoints.xy[:, 1] > my)
            & (keypoints.xy[:, 0] < width - mx)
            & (keypoints.xy[:, 1] < height - my)
        )
        if good.sum() < MIN_POINTS:
            return None
        h, inliers = fit_homography(keypoints.xy[good], KEYPOINTS_M[good])
        if h is None:
            return None
        h = orient(h, width, height)
        if not plausible(h, width, height):
            LAST_FIT["reason"] = "fora do campo"
            probe = _probe(h, width, height)
            LAST_FIT["probe"] = None if probe is None else [[round(float(v), 1) for v in pt] for pt in probe]
            return None

        # Suavização: média móvel das posições, no campo, de pontos fixos da imagem.
        control_px = CONTROL * np.array([width, height], dtype=np.float32)
        control_m = apply_h(h, control_px)
        if self.smoothed is not None and self.smoothed.shape == control_m.shape:
            control_m = SMOOTHING * control_m + (1 - SMOOTHING) * self.smoothed
        self.smoothed = control_m
        smooth_h, _ = cv2.findHomography(control_px, control_m)
        if smooth_h is None:
            return None
        h_inv = np.linalg.inv(smooth_h)
        return FieldView(h=smooth_h, h_inv=h_inv / h_inv[2, 2], points=inliers, fresh=True)


def visible_area(h: np.ndarray, width: int, height: int) -> list[list[float]] | None:
    """Polígono (em metros) da parte do campo que a câmera mostra."""
    def project(x: float, y: float) -> np.ndarray | None:
        p = h @ np.array([x, y, 1.0])
        if p[2] <= 0:
            return None
        q = p[:2] / p[2]
        if not (-40 < q[0] < LENGTH + 40 and -40 < q[1] < WIDTH + 40):
            return None
        return q

    corners = []
    for x, top_down in ((0.0, True), (float(width), True), (float(width), False), (0.0, False)):
        if top_down:
            # O alto da imagem costuma ser arquibancada: desce até achar o gramado.
            point = None
            for y in np.linspace(0, height * 0.9, 19):
                point = project(x, float(y))
                if point is not None:
                    break
        else:
            point = project(x, float(height))
        if point is None:
            return None
        corners.append([round(float(point[0]), 2), round(float(point[1]), 2)])
    return corners


# ---------------------------------------------------------------------------
# Cortes de câmera e closes
# ---------------------------------------------------------------------------

CUT_CORRELATION = 0.55


class CutDetector:
    """Compara o histograma de cor com o frame anterior: queda brusca = corte de câmera."""

    def __init__(self) -> None:
        self.prev: np.ndarray | None = None

    def reset(self) -> None:
        self.prev = None

    def update(self, image: np.ndarray) -> bool:
        small = cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [30, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        cut = False
        if self.prev is not None:
            cut = cv2.compareHist(self.prev, hist, cv2.HISTCMP_CORREL) < CUT_CORRELATION
        self.prev = hist
        return bool(cut)


def is_close_up(people: list[Any], height: int) -> bool:
    if not people:
        return False
    tallest = max(b.y2 - b.y1 for b in people)
    return tallest >= CLOSE_UP_HEIGHT_RATIO * height
