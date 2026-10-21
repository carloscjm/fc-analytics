"""Detecção de jogadores e bola com Ultralytics YOLO.

Modelos aceitos:
- oficiais YOLO26 (n, s, m, l, x), treinados no COCO: usamos as classes
  "person" e "sports ball", rotuladas como "pessoa" e "bola";
- qualquer arquivo .pt colocado em backend/models/ (por exemplo, um modelo
  treinado em futebol com as classes player, goalkeeper, referee e ball).

Os pesos oficiais são baixados automaticamente na primeira vez que forem usados
e ficam em backend/models/.
"""

from __future__ import annotations

import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
OFFICIAL_MODELS = ["yolo26n.pt", "yolo26s.pt", "yolo26m.pt", "yolo26l.pt", "yolo26x.pt"]
DEFAULT_MODEL = os.environ.get("FCA_MODEL", "yolo26s.pt")
# Modelo YOLOv8x treinado em futebol pelo projeto roboflow/sports (licença AGPL-3.0,
# dataset CC BY 4.0), com as classes ball, goalkeeper, player e referee.
# O endereço é o mesmo usado pelo setup.sh de examples/soccer daquele repositório.
FOOTBALL_MODEL_FILE = "football-player-detection.pt"
FOOTBALL_MODEL_URL = "https://drive.google.com/uc?id=17PXFNlx-jI7VjVo_vQnB1sONjRyvoB-q"

# O último modelo escolhido na página fica salvo aqui e vale nas próximas vezes.
CHOICE_FILE = "modelo-escolhido.txt"
IMGSZ_OPTIONS = [640, 960, 1280]
DEFAULT_IMGSZ = int(os.environ.get("FCA_IMGSZ", "960"))

# Orçamento de tempo de inferência por frame para a recomendação do benchmark.
# As fases 2 e 3 vão somar tracking e detecção do campo no mesmo frame,
# então a detecção de jogadores deve usar no máximo cerca de um terço de um
# intervalo de 150 ms.
BUDGET_MS = 50.0

COCO_LABELS = {"person": "pessoa", "sports ball": "bola"}
FOOTBALL_LABELS = {
    "player": "jogador",
    "players": "jogador",
    "goalkeeper": "goleiro",
    "referee": "árbitro",
    "ball": "bola",
    "football": "bola",
}


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float
    label: str

    def to_json(self) -> dict[str, Any]:
        return {"b": [self.x1, self.y1, self.x2, self.y2], "c": round(self.conf, 3), "l": self.label}


@dataclass
class DetectionResult:
    boxes: list[Box]
    width: int
    height: int
    infer_ms: float


@dataclass
class _Loaded:
    name: str
    model: Any
    class_filter: list[int] | None
    labels: dict[int, str] = field(default_factory=dict)


def decode_jpeg(jpeg: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("não foi possível decodificar o JPEG")
    return image


def _pick_device() -> tuple[str, str, bool]:
    """Retorna (dispositivo, nome legível, usar meia precisão)."""
    import torch

    if torch.cuda.is_available():
        return "cuda:0", torch.cuda.get_device_name(0), True
    return "cpu", "CPU (sem GPU NVIDIA disponível)", False


class Detector:
    def __init__(self, models_dir: Path = MODELS_DIR) -> None:
        self.models_dir = models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.device, self.device_name, self.half = _pick_device()
        self.imgsz = DEFAULT_IMGSZ if DEFAULT_IMGSZ in IMGSZ_OPTIONS else 960
        self.conf = 0.25
        self._active: _Loaded | None = None
        self._lock = threading.Lock()

    # ---------- modelos ----------

    def available_models(self) -> list[str]:
        # O modelo de pontos-chave do campo (Fase 3) não é um detector de jogadores.
        skip = set(OFFICIAL_MODELS) | {"football-pitch-detection.pt"}
        local = sorted(p.name for p in self.models_dir.glob("*.pt") if p.name not in skip)
        return OFFICIAL_MODELS + local

    @property
    def model_name(self) -> str | None:
        return self._active.name if self._active else None

    def _load(self, name: str) -> _Loaded:
        from ultralytics import YOLO

        if name not in self.available_models():
            raise ValueError(f"modelo desconhecido: {name}")
        path = self.models_dir / name
        if not path.exists() and name not in OFFICIAL_MODELS:
            raise ValueError(f"arquivo não encontrado: {path}")

        # Para os oficiais, a Ultralytics baixa o arquivo no caminho indicado.
        model = YOLO(str(path))
        names: dict[int, str] = dict(model.names)

        if "sports ball" in names.values():
            wanted = {i: COCO_LABELS[n] for i, n in names.items() if n in COCO_LABELS}
            class_filter: list[int] | None = sorted(wanted)
        else:
            wanted = {i: FOOTBALL_LABELS.get(n.lower(), n) for i, n in names.items()}
            class_filter = None

        loaded = _Loaded(name=name, model=model, class_filter=class_filter, labels=wanted)
        self._warmup(loaded)
        return loaded

    def _warmup(self, loaded: _Loaded, runs: int = 2) -> None:
        blank = np.zeros((720, 1280, 3), dtype=np.uint8)
        for _ in range(runs):
            self._predict(loaded, blank, self.imgsz)

    def set_model(self, name: str, remember: bool = True) -> None:
        loaded = self._load(name)
        with self._lock:
            self._active = loaded
        if remember:
            (self.models_dir / CHOICE_FILE).write_text(name, encoding="utf-8")

    def saved_choice(self) -> str | None:
        path = self.models_dir / CHOICE_FILE
        if not path.exists():
            return None
        name = path.read_text(encoding="utf-8").strip()
        return name if name in self.available_models() else None

    def ensure_model(self) -> None:
        if self._active is None:
            env = os.environ.get("FCA_MODEL")
            name = env or self.saved_choice() or DEFAULT_MODEL
            if name not in self.available_models():
                name = OFFICIAL_MODELS[1]
            self.set_model(name, remember=False)

    def download_football_model(self) -> Path:
        """Baixa o modelo de futebol (só quando a pessoa pede pela página)."""
        import gdown

        target = self.models_dir / FOOTBALL_MODEL_FILE
        if target.exists():
            return target
        partial = target.with_suffix(".part")
        result = gdown.download(FOOTBALL_MODEL_URL, str(partial), quiet=True)
        if not result or not partial.exists() or partial.stat().st_size < 1_000_000:
            partial.unlink(missing_ok=True)
            raise RuntimeError("o download não foi concluído")
        partial.replace(target)
        return target

    def set_imgsz(self, imgsz: int) -> None:
        if imgsz not in IMGSZ_OPTIONS:
            raise ValueError(f"resolução inválida: {imgsz}")
        self.imgsz = imgsz

    # ---------- inferência ----------

    def _predict(self, loaded: _Loaded, image: np.ndarray, imgsz: int) -> Any:
        return loaded.model.predict(
            image,
            imgsz=imgsz,
            conf=self.conf,
            classes=loaded.class_filter,
            device=self.device,
            quantize=16 if self.half else None,
            verbose=False,
        )[0]

    def detect(self, image: np.ndarray) -> DetectionResult:
        self.ensure_model()
        with self._lock:
            loaded = self._active
            assert loaded is not None
            start = time.perf_counter()
            result = self._predict(loaded, image, self.imgsz)
            infer_ms = (time.perf_counter() - start) * 1000

        boxes: list[Box] = []
        data = result.boxes
        if data is not None and len(data):
            xyxy = data.xyxy.cpu().numpy().round().astype(int)
            confs = data.conf.cpu().numpy()
            classes = data.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), conf, cls in zip(xyxy, confs, classes):
                boxes.append(
                    Box(int(x1), int(y1), int(x2), int(y2), float(conf), loaded.labels.get(int(cls), str(cls)))
                )

        height, width = image.shape[:2]
        return DetectionResult(boxes=boxes, width=width, height=height, infer_ms=infer_ms)

    # ---------- benchmark ----------

    def benchmark(self, frames: list[np.ndarray], names: list[str] | None = None, runs: int = 30) -> dict[str, Any]:
        """Mede o tempo de inferência de cada modelo nos frames recebidos.

        Usa os frames reais da transmissão quando houver; sem frames, usa uma imagem vazia.
        Bloqueia a detecção normal enquanto mede.
        """
        if not frames:
            frames = [np.zeros((720, 1280, 3), dtype=np.uint8)]
        names = names or OFFICIAL_MODELS
        rows: list[dict[str, Any]] = []

        with self._lock:
            for name in names:
                try:
                    loaded = self._load(name)
                except Exception as exc:  # noqa: BLE001 - reportado ao usuário
                    rows.append({"model": name, "error": str(exc)})
                    continue
                times: list[float] = []
                for i in range(runs):
                    frame = frames[i % len(frames)]
                    start = time.perf_counter()
                    self._predict(loaded, frame, self.imgsz)
                    times.append((time.perf_counter() - start) * 1000)
                times.sort()
                p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
                mean = statistics.fmean(times)
                rows.append(
                    {
                        "model": name,
                        "meanMs": round(mean, 1),
                        "p95Ms": round(p95, 1),
                        "fps": round(1000 / mean, 1),
                    }
                )
                del loaded

        fitting = [r for r in rows if "p95Ms" in r and r["p95Ms"] <= BUDGET_MS]
        recommended = fitting[-1]["model"] if fitting else None
        return {
            "rows": rows,
            "imgsz": self.imgsz,
            "budgetMs": BUDGET_MS,
            "frames": len(frames),
            "recommended": recommended,
            "device": self.device_name,
        }
