"""Teste com o YOLO de verdade numa foto de exemplo da Ultralytics.

Roda na CPU se não houver GPU. Na primeira execução baixa o yolo26n.pt (cerca de 5 MB).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ultralytics = pytest.importorskip("ultralytics")

from app.detector import Detector  # noqa: E402


@pytest.fixture(scope="module")
def bus_image():
    import cv2

    path = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    image = cv2.imread(str(path))
    assert image is not None
    return image


def test_detects_people(tmp_path_factory, bus_image):
    models_dir = Path(__file__).resolve().parent.parent / "models"
    detector = Detector(models_dir=models_dir)
    detector.set_imgsz(640)
    detector.set_model("yolo26n.pt")

    result = detector.detect(bus_image)

    people = [b for b in result.boxes if b.label == "pessoa"]
    assert len(people) >= 3
    assert all(b.label in {"pessoa", "bola"} for b in result.boxes)
    assert result.infer_ms > 0
    assert (result.width, result.height) == (bus_image.shape[1], bus_image.shape[0])


def test_benchmark_recommends_a_model(bus_image):
    models_dir = Path(__file__).resolve().parent.parent / "models"
    detector = Detector(models_dir=models_dir)
    detector.set_imgsz(640)
    report = detector.benchmark([bus_image], names=["yolo26n.pt"], runs=3)
    assert report["rows"][0]["model"] == "yolo26n.pt"
    assert report["rows"][0]["meanMs"] > 0


def test_remembers_chosen_model(tmp_path):
    detector = Detector(models_dir=tmp_path)
    detector.set_imgsz(640)
    assert detector.saved_choice() is None
    (tmp_path / "yolo26n.pt").write_bytes((Path(__file__).resolve().parent.parent / "models" / "yolo26n.pt").read_bytes())
    detector.set_model("yolo26n.pt")
    assert Detector(models_dir=tmp_path).saved_choice() == "yolo26n.pt"
