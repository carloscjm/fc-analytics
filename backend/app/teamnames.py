"""Nomes dos times lidos do placar da transmissão.

A cada poucos segundos, a faixa de cima da imagem (onde fica o placar) passa
por um leitor de texto local (RapidOCR, Apache 2.0, roda na CPU). O leitor
procura duas siglas de 2 a 4 letras maiúsculas lado a lado, normalmente com o
placar no meio ("MCI 0 3 PSG", "VAS 0-2 BOC"), ou uma embaixo da outra nos
placares em pilha. Quando o mesmo par aparece algumas vezes, ele vira o nome
dos times.

Qual sigla é de qual camisa: muitos placares têm um retângulo com a cor do
time ao lado da sigla; quando dá para ler essas cores, elas decidem. Senão, a
primeira sigla fica com o time de camisa mais clara (Time A), e a pessoa pode
trocar com um clique. Os nomes ficam presos à cor da camisa, então continuam
certos mesmo se a calibração dos times recomeçar.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

log = logging.getLogger("fc-analytics")

BAND_TOP = 0.28  # o placar fica quase sempre no alto da tela
READ_EVERY_S = 6.0  # enquanto ainda não tem os nomes
CONFIRMED_EVERY_S = 60.0  # depois, só confere de vez em quando
VOTES_TO_CONFIRM = 3
MAX_NAME_LEN = 12

# Siglas que aparecem na tela mas não são times.
NOT_TEAMS = {
    "VAR", "HD", "AO", "VIVO", "LIVE", "TNT", "ESPN", "FT", "HT", "AET", "PEN", "UEFA", "CBF", "TV", "SBT",
    "GE", "FOX", "BBC", "ITV", "DAZN", "GOL", "VS", "MIN", "INT", "MAX", "SKY", "CAZE", "ST", "ND", "RD", "TH",
    "OK", "FIFA", "CONMEBOL", "AFA", "LFP", "EPL", "NBA", "PREMIUM",
}

TOKEN = re.compile(r"^[A-Z]{2,4}$")
# Duas siglas separadas por espaço ou pelo placar ("MCI 0 3 PSG", "VAS 0-2 BOC", "FLA x PAL").
LINE_PAIR = re.compile(
    r"(?<![A-Z])([A-Z]{2,4})(?:\s+|\s*(?:\d{1,2}\s*[-–:x]?\s*\d{1,2}|\d{1,2}|[-–:])\s*|\s+x\s+)([A-Z]{2,4})(?![A-Z])"
)


@dataclass
class Token:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float

    @property
    def h(self) -> float:
        return max(1.0, self.y1 - self.y0)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def _tokens(result: Any) -> list[Token]:
    out = []
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None) or ()
    scores = getattr(result, "scores", None) or ()
    if boxes is None:
        return out
    for box, text, score in zip(boxes, txts, scores):
        pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
        out.append(Token(str(text).strip(), float(pts[:, 0].min()), float(pts[:, 1].min()),
                         float(pts[:, 0].max()), float(pts[:, 1].max()), float(score)))
    return out


def find_pair(tokens: list[Token]) -> tuple[tuple[str, str], tuple[Token | None, Token | None]] | None:
    """As duas siglas do placar, na ordem em que aparecem (esquerda → direita ou cima → baixo)."""
    def ok(name: str) -> bool:
        return bool(TOKEN.match(name)) and name not in NOT_TEAMS

    # 1) Tudo num token só: "MCI 0 3 PSG".
    for tok in sorted(tokens, key=lambda t: -t.score):
        for m in LINE_PAIR.finditer(tok.text.upper()):
            a, b = m.group(1), m.group(2)
            if ok(a) and ok(b) and a != b:
                return (a, b), (tok, tok)

    # 1b) O leitor às vezes quebra o placar em pedaços ("MCI" + "0 3 PSG"): junta os pedaços da mesma linha.
    for line in _lines(tokens):
        text = " ".join(t.text.upper() for t in line)
        for m in LINE_PAIR.finditer(text):
            a, b = m.group(1), m.group(2)
            if ok(a) and ok(b) and a != b:
                return (a, b), (_owner(line, a), _owner(line, b))

    singles = [t for t in tokens if ok(t.text.upper()) and t.score >= 0.8]
    # 2) Na mesma linha, perto uma da outra (com o placar entre elas ou não): "VAS" "0-2" "BOC".
    best = None
    for i, a in enumerate(singles):
        for b in singles[i + 1 :]:
            left, right = (a, b) if a.x0 <= b.x0 else (b, a)
            same_line = abs(a.cy - b.cy) <= 0.5 * max(a.h, b.h)
            gap = right.x0 - left.x1
            if same_line and 0 <= gap <= 8 * max(a.h, b.h) and left.text != right.text:
                cand = (gap, (left.text.upper(), right.text.upper()), (left, right))
                if best is None or cand[0] < best[0]:
                    best = cand
    if best:
        return best[1], best[2]
    # 3) Placar em pilha: uma sigla embaixo da outra, alinhadas à esquerda.
    for i, a in enumerate(singles):
        for b in singles[i + 1 :]:
            top, bottom = (a, b) if a.cy <= b.cy else (b, a)
            if abs(a.x0 - b.x0) <= max(a.h, b.h) and 0 < bottom.cy - top.cy <= 2.5 * max(a.h, b.h) and a.text != b.text:
                return (top.text.upper(), bottom.text.upper()), (top, bottom)
    return None


def _lines(tokens: list[Token]) -> list[list[Token]]:
    """Pedaços de texto vizinhos na mesma linha (pequeno espaço entre eles), da esquerda para a direita."""
    out: list[list[Token]] = []
    for t in sorted(tokens, key=lambda t: t.x0):
        for line in out:
            last = line[-1]
            h = max(last.h, t.h)
            # Pedaços podem se sobrepor um pouco (caixas do leitor de texto não são exatas).
            if abs(last.cy - t.cy) <= 0.5 * h and -0.6 * h <= t.x0 - last.x1 <= 3 * h:
                line.append(t)
                break
        else:
            out.append([t])
    return [line for line in out if len(line) > 1]


def _owner(line: list[Token], name: str) -> Token | None:
    return next((t for t in line if name in t.text.upper().split()), None)


def chip_color(image: np.ndarray, tok: Token | None, side: str) -> np.ndarray | None:
    """Cor (Lab) do retângulo que muitos placares põem ao lado da sigla, se houver um bem colorido."""
    if tok is None:
        return None
    h = tok.h
    if side == "left":
        x0, x1 = int(tok.x0 - 1.0 * h), int(tok.x0 - 0.15 * h)
    else:
        x0, x1 = int(tok.x1 + 0.15 * h), int(tok.x1 + 1.0 * h)
    y0, y1 = int(tok.y0), int(tok.y1)
    H, W = image.shape[:2]
    x0, x1, y0, y1 = max(0, x0), min(W, x1), max(0, y0), min(H, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    patch = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    # Só vale um retângulo de cor viva e uniforme (não o fundo cinza/preto do placar).
    if float(np.median(hsv[:, 1])) < 90 or float(np.std(hsv[:, 0])) > 12:
        return None
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    return np.median(lab, axis=0)


def hex_to_lab(color: str) -> np.ndarray:
    c = color.lstrip("#")
    bgr = np.array([[[int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16)]]], dtype=np.uint8)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).reshape(3).astype(np.float32)


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()[:MAX_NAME_LEN]


@dataclass
class TeamNames:
    """Nomes ligados à cor da camisa. `names[i]` acompanha a cor `anchors[i]` (hex)."""

    names: list[str] = field(default_factory=list)
    anchors: list[str] | None = None
    source: str | None = None  # "placar" ou "manual"

    def ordered(self, colors: list[str] | None) -> list[str | None]:
        """Nomes na ordem dos times atuais (0 = Time A, 1 = Time B)."""
        if len(self.names) != 2:
            return [None, None]
        if not colors or not self.anchors:
            return list(self.names)
        a = [hex_to_lab(c) for c in self.anchors]
        c = [hex_to_lab(x) for x in colors]
        straight = np.linalg.norm(a[0] - c[0]) + np.linalg.norm(a[1] - c[1])
        crossed = np.linalg.norm(a[0] - c[1]) + np.linalg.norm(a[1] - c[0])
        return list(self.names) if straight <= crossed else [self.names[1], self.names[0]]

    def to_json(self) -> dict[str, Any]:
        return {"names": self.names, "anchors": self.anchors, "source": self.source}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> TeamNames:
        if not data:
            return cls()
        return cls(names=list(data.get("names") or []), anchors=data.get("anchors"), source=data.get("source"))


class TeamNameReader:
    """Lê o placar em segundo plano e decide os nomes quando o mesmo par aparece algumas vezes."""

    def __init__(self, engine_factory=None, clock=time.monotonic) -> None:
        self._engine_factory = engine_factory
        self._engine = None
        self.available: bool | None = None  # None = ainda não tentou carregar
        self._retry_at = 0.0
        self.error: str | None = None
        self.clock = clock
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.votes: Counter[tuple[str, str]] = Counter()
        self.chips: dict[tuple[str, str], list[tuple[np.ndarray, np.ndarray]]] = {}
        self.confirmed: tuple[str, str] | None = None
        self.next_at = 0.0
        self.busy = False
        self.reads = 0

    def _get_engine(self):
        if self._engine is None and (self.available is not False or self.clock() >= self._retry_at):
            try:
                if self._engine_factory is not None:
                    self._engine = self._engine_factory()
                else:
                    from rapidocr import RapidOCR

                    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                    self._engine = RapidOCR()
                self.available = True
            except Exception as exc:  # noqa: BLE001
                # Pode ser a biblioteca ainda sendo instalada pela atualização: tenta de novo em 1 minuto.
                self.available = False
                self._retry_at = self.clock() + 60.0
                self.error = f"leitor de placar indisponível: {exc}"
                log.warning(self.error)
        return self._engine

    def maybe_read(self, image: np.ndarray, on_done=None) -> None:
        now = self.clock()
        with self._lock:
            if self.busy or now < self.next_at or (self.available is False and now < self._retry_at):
                return
            self.busy = True
            self.next_at = now + (CONFIRMED_EVERY_S if self.confirmed else READ_EVERY_S)
        band = image[: max(1, int(image.shape[0] * BAND_TOP))].copy()

        def work() -> None:
            try:
                self.read(band)
            except Exception:  # noqa: BLE001
                log.exception("falha ao ler o placar")
            finally:
                with self._lock:
                    self.busy = False
            if on_done is not None:
                on_done()

        threading.Thread(target=work, daemon=True).start()

    def read(self, band: np.ndarray) -> tuple[str, str] | None:
        engine = self._get_engine()
        if engine is None:
            return None
        pair = find_pair(_tokens(engine(band)))
        with self._lock:
            self.reads += 1
            if pair is None:
                return None
            names, (left, right) = pair
            self.votes[names] += 1
            same_token = left is right
            c1 = None if same_token else chip_color(band, left, "left")
            c2 = None if same_token else chip_color(band, right, "right")
            if c1 is not None and c2 is not None and float(np.linalg.norm(c1 - c2)) > 25:
                self.chips.setdefault(names, []).append((c1, c2))
            top, count = self.votes.most_common(1)[0]
            total = sum(self.votes.values())
            if count >= VOTES_TO_CONFIRM and count / total >= 0.6:
                self.confirmed = top
            return names

    def decide(self, team_colors: list[str] | None) -> TeamNames | None:
        """Nomes confirmados, já ligados às cores das camisas (se der para saber pelas cores do placar)."""
        with self._lock:
            if self.confirmed is None:
                return None
            names = list(self.confirmed)
            chips = self.chips.get(self.confirmed) or []
        if not team_colors:
            return TeamNames(names=names, anchors=None, source="placar")
        team_lab = [hex_to_lab(c) for c in team_colors]
        if chips:
            c1 = np.median([c[0] for c in chips], axis=0)
            c2 = np.median([c[1] for c in chips], axis=0)
            straight = np.linalg.norm(c1 - team_lab[0]) + np.linalg.norm(c2 - team_lab[1])
            crossed = np.linalg.norm(c1 - team_lab[1]) + np.linalg.norm(c2 - team_lab[0])
            if crossed + 15 < straight:
                names = [names[1], names[0]]
        return TeamNames(names=names, anchors=list(team_colors), source="placar")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self.available,
                "reads": self.reads,
                "candidates": [{"names": list(k), "votes": v} for k, v in self.votes.most_common(3)],
                "confirmed": list(self.confirmed) if self.confirmed else None,
                "error": self.error,
            }


def clean_names(names: list[Any]) -> list[str]:
    if not isinstance(names, list) or len(names) != 2:
        raise ValueError("informe os dois nomes")
    out = [_clean(n) for n in names]
    if not all(out):
        raise ValueError("os nomes não podem ficar vazios")
    return out
