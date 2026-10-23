"""Cards do Instagram (carrossel vertical, 1080 × 1350) em SVG.

O conteúdo vem de `story.Story` (dados oficiais + análise por vídeo); aqui só se
desenha, sempre com a mesma identidade: gramado listrado, moldura de giz,
títulos em Anton, números grandes, campinhos verticais com o time atacando para
cima e as cores das camisas (mais fortes). O SVG não quebra linhas sozinho, então
os textos são quebrados aqui com as larguras reais das fontes (`assets/fonts/metrics.json`).

As fontes (Anton, Barlow Condensed e Inter, licença OFL) vão embutidas no SVG
quando ele vira imagem (`embed_fonts=True`); no relatório elas são declaradas uma
vez na página.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

from .pitch import LENGTH as L
from .pitch import WIDTH as W
from .report import vivid
from .story import Story, team_names

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
CW, CH = 1080, 1350
PAD = 84
INNER = CW - 2 * PAD
TURF, TURF2 = "#0c2f22", "#12402e"
CHALK, MUTED = "#f4f1e8", "#a9bfb2"
DEFAULT_COLORS = ("#f5c400", "#f0640a")

FONT_FILES = {
    "anton": ("FCA Anton", 400),
    "barlow-condensed-700": ("FCA Barlow", 700),
    "barlow-condensed-800": ("FCA Barlow", 800),
    "inter-500": ("FCA Inter", 500),
    "inter-700": ("FCA Inter", 700),
}


@lru_cache(maxsize=1)
def _metrics() -> dict[str, Any]:
    return json.loads((FONTS_DIR / "metrics.json").read_text(encoding="utf-8"))


def text_width(text: str, font: str, size: float, spacing: float = 0.0) -> float:
    m = _metrics()[font]
    widths, default = m["widths"], m["default"]
    return sum(widths.get(ch, default) for ch in text) * size + spacing * max(0, len(text) - 1)


@lru_cache(maxsize=2)
def font_css(embed: bool = True) -> str:
    """@font-face das fontes dos cards (embutidas em base64, para o SVG virar imagem sem buscar nada)."""
    out = []
    for stem, (family, weight) in FONT_FILES.items():
        path = FONTS_DIR / f"{stem}.woff2"
        src = (
            f"url(data:font/woff2;base64,{base64.b64encode(path.read_bytes()).decode()}) format('woff2')"
            if embed
            else f"url({stem}.woff2) format('woff2')"
        )
        out.append(f"@font-face{{font-family:'{family}';font-weight:{weight};src:{src};}}")
    return "".join(out)


# ---------------------------------------------------------------------------
# Texto com quebra de linha e nomes dos times coloridos
# ---------------------------------------------------------------------------

def _tokens(text: str, names: list[str], colors: list[str]) -> list[tuple[str, str | None]]:
    """Palavras do texto; as que formam o nome de um time levam a cor dele."""
    words = text.split()
    name_words = [(n.split(), colors[i]) for i, n in enumerate(names) if n]
    name_words.sort(key=lambda nw: -len(nw[0]))
    out: list[tuple[str, str | None]] = []
    i = 0
    while i < len(words):
        for parts, color in name_words:
            k = len(parts)
            chunk = words[i : i + k]
            if len(chunk) == k and all(a.strip(".,:;!?()") == b for a, b in zip(chunk, parts)):
                out.extend((w, color) for w in chunk)
                i += k
                break
        else:
            out.append((words[i], None))
            i += 1
    return out


def wrap(text: str, font: str, size: float, width: float, names: list[str] | None = None,
         colors: list[str] | None = None, upper: bool = False, spacing: float = 0.0) -> list[list[tuple[str, str | None]]]:
    if upper:
        text = text.upper()
        names = [n.upper() for n in (names or [])]
    tokens = _tokens(text, names or [], colors or [])
    space = text_width(" ", font, size) + spacing
    lines: list[list[tuple[str, str | None]]] = [[]]
    used = 0.0
    for word, color in tokens:
        w = text_width(word, font, size, spacing)
        if lines[-1] and used + space + w > width:
            lines.append([])
            used = 0.0
        used += (space if lines[-1] else 0) + w
        lines[-1].append((word, color))
    return lines


def text_block(x: float, y: float, text: str, font: str, size: float, line_height: float, width: float, *,
               fill: str = CHALK, names: list[str] | None = None, colors: list[str] | None = None,
               upper: bool = False, spacing: float = 0.0, bold_names: bool = True, anchor: str = "start",
               max_lines: int | None = None) -> tuple[str, float]:
    """SVG de um bloco de texto que começa em y (topo); devolve (svg, altura)."""
    family, weight = FONT_FILES[font]
    lines = wrap(text, font, size, width, names, colors, upper, spacing)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last_word, last_color = lines[-1][-1]
        lines[-1][-1] = (last_word.rstrip(".,;:") + "…", last_color)
    out = []
    baseline = y + size * 0.78 + (line_height - size) / 2
    for i, line in enumerate(lines):
        spans = []
        for j, (word, color) in enumerate(line):
            sep = " " if j else ""
            if color:
                style = f' fill="{color}"' + (' font-weight="700"' if bold_names and font.startswith("inter") else "")
                spans.append(f'{sep}<tspan{style}>{escape(word)}</tspan>')
            else:
                spans.append(f"{sep}{escape(word)}")
        out.append(
            f'<text x="{x:.1f}" y="{baseline + i * line_height:.1f}" font-family="{family}" font-weight="{weight}" '
            f'font-size="{size}" fill="{fill}" letter-spacing="{spacing}" text-anchor="{anchor}" xml:space="preserve">'
            f'{"".join(spans)}</text>'
        )
    return "".join(out), len(lines) * line_height


# ---------------------------------------------------------------------------
# Campinhos verticais (o time ataca para cima)
# ---------------------------------------------------------------------------

def rot(x: float, y: float) -> tuple[float, float]:
    """Normalizado (atacando para a direita, esquerda do time em y pequeno) → vertical, atacando para cima."""
    return y, L - x


def pitch_svg(x: float, y: float, height: float, content: str, y0: float = -4.0, pad: float = 4.0) -> tuple[str, float]:
    """Campo vertical recortado de `y0` (em metros, 0 = linha de fundo de cima) até a linha de fundo de baixo."""
    vb_h = L + pad - y0
    vb_w = W + 2 * pad
    width = height * vb_w / vb_h
    lines = [
        f'<rect x="0" y="0" width="{W}" height="{L}"/>',
        f'<line x1="0" y1="{L / 2}" x2="{W}" y2="{L / 2}"/>',
        f'<circle cx="{W / 2}" cy="{L / 2}" r="9.15"/>',
    ]
    for top in (True, False):
        for bw, bl in ((40.32, 16.5), (18.32, 5.5)):
            lines.append(f'<rect x="{(W - bw) / 2}" y="{0 if top else L - bl}" width="{bw}" height="{bl}"/>')
    stripes = "".join(
        f'<rect x="0" y="{i * L / 10}" width="{W}" height="{L / 10}" fill="#fff" opacity=".035"/>' for i in range(1, 10, 2)
    )
    svg = (
        f'<svg x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" viewBox="{-pad} {y0} {vb_w} {vb_h}">'
        f'<rect x="{-pad}" y="{y0}" width="{vb_w}" height="{vb_h}" fill="#0f3d2b"/>{stripes}'
        f'<g fill="none" stroke="rgba(255,255,255,.55)" stroke-width=".35">{"".join(lines)}</g>{content}</svg>'
    )
    return svg, width


def dot(x: float, y: float, color: str, name: str, strong: bool = False, faded: bool = False) -> str:
    X, Y = rot(x, y)
    ring = f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="4.2" fill="none" stroke="#fff" stroke-width=".7"/>' if strong else ""
    label = "" if faded else (
        f'<text x="{X:.1f}" y="{Y + 6.4:.1f}" font-family="FCA Barlow" font-weight="800" font-size="4.3" fill="#fff" '
        f'text-anchor="middle" stroke="rgba(0,0,0,.7)" stroke-width=".9" paint-order="stroke">{escape(name)}</text>'
    )
    return (
        f'<g opacity="{0.35 if faded else 1}">{ring}<circle cx="{X:.1f}" cy="{Y:.1f}" r="2.6" fill="{color}" '
        f'stroke="#0b1a12" stroke-width=".5"/>{label}</g>'
    )


def arrow(a: list[float], b: list[float]) -> str:
    (x0, y0), (x1, y1) = rot(*a), rot(*b)
    return (
        f'<path d="M{x0:.1f},{y0:.1f} L{x1:.1f},{y1 + 4:.1f}" stroke="#fff" stroke-width="1.1" stroke-dasharray="2 1.4" '
        f'fill="none" marker-end="url(#fca-head)" opacity=".9"/>'
    )


# ---------------------------------------------------------------------------
# Peças comuns
# ---------------------------------------------------------------------------

def _luma(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _lighten(color: str, amount: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(round(c + (255 - c) * amount) for c in (r, g, b)))


def card_colors(stats: dict[str, Any]) -> list[str]:
    """Cores das camisas, mais fortes e sempre legíveis no gramado escuro."""
    raw = stats.get("teamColors") or [None, None]
    out = []
    for i in (0, 1):
        color = vivid(raw[i] if i < len(raw) else None, DEFAULT_COLORS[i])
        if _luma(color) < 0.3:
            color = _lighten(color, 0.45)
        out.append(color)
    return out


class Canvas:
    def __init__(self, index: int, total: int, top_left: str, top_right: str):
        self.parts: list[str] = []
        self.y = float(PAD)
        self.index, self.total = index, total
        self.parts.append(
            f'<text x="{PAD}" y="{PAD + 22}" font-family="FCA Barlow" font-weight="700" font-size="30" fill="{MUTED}" '
            f'letter-spacing="2.4">{escape(top_left.upper())}</text>'
            f'<text x="{CW - PAD}" y="{PAD + 22}" font-family="FCA Barlow" font-weight="700" font-size="30" fill="{MUTED}" '
            f'letter-spacing="2.4" text-anchor="end">{escape(top_right.upper())}</text>'
        )
        self.y = PAD + 30
        self.body_from = len(self.parts)
        self.shift = 0.0
        self.fixed: list[str] = []

    def balance(self, bottom: float = CH - 130) -> None:
        """Desce o conteúdo para dividir o espaço que sobrou (evita card vazio embaixo)."""
        self.shift = max(0.0, (bottom - self.y) * 0.4)

    def add(self, svg: str, height: float, gap: float = 0.0) -> None:
        self.parts.append(svg)
        self.y += height + gap

    def title(self, text: str, size: int = 92, gap_before: int = 48) -> None:
        self.y += gap_before
        svg, h = text_block(PAD, self.y, text, "anton", size, size * 1.0, INNER, upper=True)
        self.add(svg, h)

    def lead(self, text: str, names: list[str], colors: list[str], size: int = 40, gap_before: int = 34) -> None:
        self.y += gap_before
        svg, h = text_block(PAD, self.y, text, "inter-500", size, size * 1.38, INNER - 40, names=names, colors=colors)
        self.add(svg, h)

    def footer(self, left: str = "Arraste →") -> None:
        y = CH - 72
        self.fixed.append(
            f'<text x="{PAD}" y="{y}" font-family="FCA Barlow" font-weight="700" font-size="28" fill="{MUTED}" '
            f'letter-spacing="1.7">{escape(left.upper())}</text>'
            f'<text x="{CW - PAD}" y="{y}" font-family="FCA Barlow" font-weight="700" font-size="28" fill="{MUTED}" '
            f'letter-spacing="1.7" text-anchor="end">{self.index}/{self.total}</text>'
        )

    def svg(self, embed_fonts: bool) -> str:
        stripes = "".join(
            f'<rect x="0" y="{i * 135}" width="{CW}" height="135" fill="{TURF2}"/>' for i in range(1, 10, 2)
        )
        style = f"<style>{font_css(True)}</style>" if embed_fonts else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{CW}" height="{CH}" viewBox="0 0 {CW} {CH}">{style}'
            '<defs><marker id="fca-head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2.2" markerHeight="2.2" '
            'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#fff"/></marker></defs>'
            f'<rect width="{CW}" height="{CH}" fill="{TURF}"/>{stripes}'
            f'<rect x="36" y="36" width="{CW - 72}" height="{CH - 72}" rx="6" fill="none" stroke="{CHALK}" '
            f'stroke-opacity=".28" stroke-width="3"/>{"".join(self.parts[:self.body_from])}'
            f'<g transform="translate(0 {self.shift:.1f})">{"".join(self.parts[self.body_from:])}</g>{"".join(self.fixed)}</svg>'
        ).replace("fca-head", f"fca-head-{self.index}")  # ids únicos quando vários cards ficam na mesma página


def _big(x: float, y: float, value: str, caption: str, color: str, width: float, size: int = 120,
         caption_size: int = 32) -> tuple[str, float]:
    num, h1 = text_block(x, y, value, "anton", size, size * 0.95, width, fill=color)
    cap, h2 = text_block(x, y + h1 + 8, caption, "barlow-condensed-700", caption_size, caption_size * 1.15, width,
                         fill=MUTED, upper=True, spacing=1.2)
    return num + cap, h1 + 8 + h2


# ---------------------------------------------------------------------------
# Cada tipo de card
# ---------------------------------------------------------------------------

def _cover(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    score = card.get("score")
    c.y += 54
    if score is not None:
        size_name = 46
        score_text = f"{score[0]}  x  {score[1]}"
        while size_name > 30:
            wa = text_width(names[0].upper(), "barlow-condensed-800", size_name, 1.8) + 34
            wb = text_width(names[1].upper(), "barlow-condensed-800", size_name, 1.8) + 34
            ws = text_width(score_text, "anton", 150)
            if wa + wb + ws + 68 <= INNER:
                break
            size_name -= 4
        x = PAD
        mid = c.y + 75
        parts = []
        for t, w in ((0, wa), (None, ws), (1, wb)):
            if t is None:
                parts.append(f'<text x="{x:.1f}" y="{mid + 52:.1f}" font-family="FCA Anton" font-size="150" fill="{CHALK}" '
                             f'xml:space="preserve">{escape(score_text)}</text>')
                x += ws + 34
                continue
            parts.append(f'<circle cx="{x + 11:.1f}" cy="{mid:.1f}" r="11" fill="{colors[t]}" stroke="rgba(0,0,0,.35)" stroke-width="2"/>')
            parts.append(f'<text x="{x + 34:.1f}" y="{mid + size_name * 0.36:.1f}" font-family="FCA Barlow" font-weight="800" '
                         f'font-size="{size_name}" fill="{colors[t]}" letter-spacing="1.8">{escape(names[t].upper())}</text>')
            x += w + 34
        c.add("".join(parts), 150)
    c.y += 20
    svg, h = text_block(PAD, c.y + 34, card["headline"], "anton", 118, 112, INNER, upper=True)
    c.add(svg, h + 34)
    c.lead(card["lead"], names, colors)
    tiles = card.get("tiles") or []
    if tiles:
        c.y += 56
        c.parts.append(f'<line x1="{PAD}" y1="{c.y}" x2="{CW - PAD}" y2="{c.y}" stroke="{CHALK}" stroke-opacity=".28" stroke-width="3"/>')
        c.y += 36
        col = (INNER - 60) / 3
        hmax = 0.0
        for i, (value, caption, team) in enumerate(tiles):
            svg, h = _big(PAD + i * (col + 30), c.y, value, caption, colors[team] if team in (0, 1) else CHALK, col, 92, 28)
            c.parts.append(svg)
            hmax = max(hmax, h)
        c.y += hmax


def _goals(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    c.title(card["title"])
    c.y += 40
    goals = card["goals"][:8]
    row = 112 if len(goals) <= 5 else 86
    for g in goals:
        t = g.get("team")
        color = colors[t] if t in (0, 1) else CHALK
        minute = (g.get("minute") or "").replace("'", "’")
        detail = []
        if g.get("penalty"):
            detail.append("pênalti")
        if g.get("ownGoal"):
            detail.append("gol contra")
        if g.get("assist"):
            detail.append(f"assistência: {g['assist']}")
        name = g.get("player") or names[t] if t in (0, 1) else "Gol"
        c.parts.append(
            f'<text x="{PAD}" y="{c.y + 54:.1f}" font-family="FCA Anton" font-size="62" fill="{color}">{escape(minute)}</text>'
            f'<circle cx="{PAD + 172}" cy="{c.y + 32:.1f}" r="11" fill="{color}" stroke="rgba(0,0,0,.35)" stroke-width="2"/>'
        )
        who, _ = text_block(PAD + 200, c.y + 6, f"{name}", "barlow-condensed-800", 46, 48, INNER - 200, upper=True, spacing=1.4, max_lines=1)
        team_line = (names[t] if t in (0, 1) else "") + (f" · {' · '.join(detail)}" if detail else "")
        sub, _ = text_block(PAD + 200, c.y + 56, team_line, "inter-500", 28, 34, INNER - 200, fill=MUTED, max_lines=1)
        c.parts.append(who + sub)
        c.y += row
    c.lead(card["lead"], names, colors, size=38, gap_before=24)


def _bars(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    c.title(card["title"])
    c.y += 56
    for label, a, b, ta, tb, note in card["bars"]:
        lab, _ = text_block(PAD, c.y, label, "barlow-condensed-800", 40, 44, INNER - 200, upper=True, spacing=1.2)
        c.parts.append(lab)
        if note:
            c.parts.append(f'<text x="{CW - PAD}" y="{c.y + 34:.1f}" font-family="FCA Barlow" font-weight="700" font-size="40" '
                           f'fill="{MUTED}" text-anchor="end">{escape(note.upper())}</text>')
        y = c.y + 58
        wa = INNER * a / 100
        c.parts.append(
            f'<clipPath id="bar{c.index}{int(y)}"><rect x="{PAD}" y="{y:.1f}" width="{INNER}" height="54" rx="6"/></clipPath>'
            f'<g clip-path="url(#bar{c.index}{int(y)})"><rect x="{PAD}" y="{y:.1f}" width="{wa:.1f}" height="54" fill="{colors[0]}"/>'
            f'<rect x="{PAD + wa:.1f}" y="{y:.1f}" width="{INNER - wa:.1f}" height="54" fill="{colors[1]}"/></g>'
            f'<text x="{PAD + 18}" y="{y + 40:.1f}" font-family="FCA Anton" font-size="36" fill="#10140f">{escape(ta)}</text>'
            f'<text x="{CW - PAD - 18}" y="{y + 40:.1f}" font-family="FCA Anton" font-size="36" fill="#10140f" text-anchor="end">{escape(tb)}</text>'
        )
        c.y = y + 54 + 46
    c.y -= 20
    legend = (
        f'<circle cx="{PAD + 11}" cy="{c.y + 14:.1f}" r="11" fill="{colors[0]}"/>'
        f'<text x="{PAD + 32}" y="{c.y + 24:.1f}" font-family="FCA Barlow" font-weight="800" font-size="32" fill="{colors[0]}" letter-spacing="1.2">{escape(names[0].upper())}</text>'
        f'<circle cx="{CW - PAD - 11}" cy="{c.y + 14:.1f}" r="11" fill="{colors[1]}"/>'
        f'<text x="{CW - PAD - 32}" y="{c.y + 24:.1f}" font-family="FCA Barlow" font-weight="800" font-size="32" fill="{colors[1]}" letter-spacing="1.2" text-anchor="end">{escape(names[1].upper())}</text>'
    )
    c.add(legend, 30)
    c.lead(card["lead"], names, colors, size=38)


def _fullbacks(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    t = card["team"]
    color = colors[t]
    c.title(card["title"])
    content = ""
    moving = {m["name"] for m in card["moves"]}
    for m in card["moves"]:
        content += arrow(m["from"], m["to"])
        X, Y = rot(*m["from"])
        content += f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="2.3" fill="none" stroke="{color}" stroke-width=".7" stroke-dasharray="1 .8"/>'
    for r in card["roles"]:
        name = r.get("name", "")
        content += dot(r["x"], r["y"], color, name, strong=name in moving, faded=name not in moving and name != "ZAG")
    top = c.y + 30
    lead_h = len(wrap(card["lead"], "inter-500", 36, INNER - 40, names, colors)) * 36 * 1.38
    ph = max(420.0, min(600.0, CH - 150 - top - 30 - lead_h))
    svg, width = pitch_svg(PAD, top, ph, content)
    c.parts.append(svg)
    side_x = PAD + width + 46
    y = top + 40
    for value, caption in card["big"]:
        big, h = _big(side_x, y, value, caption, color, CW - PAD - side_x)
        c.parts.append(big)
        y += h + 40
    c.y = top + ph
    c.lead(card["lead"], names, colors, size=36, gap_before=30)


def _block(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    t = card["team"]
    color = colors[t]
    c.title(card["title"])
    line = sorted(card.get("line") or [], key=lambda p: p["y"])
    content = ""
    if len(line) >= 2:
        pts = " ".join(f"{rot(p['x'], p['y'])[0]:.1f},{rot(p['x'], p['y'])[1]:.1f}" for p in line)
        content += f'<polyline points="{pts}" fill="none" stroke="#fff" stroke-width="1" opacity=".85"/>'
    in_line = {(round(p["x"], 1), round(p["y"], 1)) for p in line}
    highlight = set(card.get("highlight") or [])
    for r in card["roles"]:
        member = (round(r["x"], 1), round(r["y"], 1)) in in_line
        content += dot(r["x"], r["y"], color, r.get("name", ""), strong=member and r.get("name") in highlight, faded=not member)
    ys = [rot(r["x"], r["y"])[1] for r in card["roles"]]
    y0 = max(-4.0, min(L / 2 - 4, min(ys) - 10)) if ys else L / 2 - 4
    # O campinho encolhe quando o texto é longo, para não encostar no rodapé.
    lead_h = len(wrap(card["lead"], "inter-500", 37, INNER - 40, names, colors)) * 37 * 1.38
    height = max(380.0, min(560.0, CH - 150 - (c.y + 34) - 34 - lead_h))
    vb_h = L + 4 - y0
    width = height * (W + 8) / vb_h
    if width > INNER:
        height = INNER * vb_h / (W + 8)
        width = INNER
    svg, width = pitch_svg(PAD + (INNER - width) / 2, c.y + 34, height, content, y0=y0)
    c.add(svg, height + 34)
    c.lead(card["lead"], names, colors, size=37)


def _counts(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    color = colors[card["team"]]
    c.title(card["title"])
    c.y += 54
    col = (INNER - 40) / 2
    rows = [card["tiles"][i : i + 2] for i in range(0, len(card["tiles"]), 2)]
    for row in rows:
        hmax = 0.0
        for i, (value, caption, dim) in enumerate(row):
            x = PAD + i * (col + 40)
            stroke = CHALK if dim else color
            fill = CHALK if dim else color
            opacity = ".55" if dim else "1"
            c.parts.append(f'<rect x="{x:.1f}" y="{c.y:.1f}" width="{col:.1f}" height="4" fill="{stroke}" opacity="{".35" if dim else "1"}"/>')
            num, h1 = text_block(x, c.y + 18, value, "anton", 150, 140, col, fill=fill)
            c.parts.append(f'<g opacity="{opacity}">{num}</g>')
            cap, h2 = text_block(x, c.y + 18 + h1 + 10, caption, "barlow-condensed-700", 34, 39, col, upper=True, spacing=1)
            c.parts.append(cap)
            hmax = max(hmax, 18 + h1 + 10 + h2)
        c.y += hmax + 26
    c.lead(card["lead"], names, colors, size=38, gap_before=10)


def _lines(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    c.title(card["title"])
    top = c.y + 36
    col = (INNER - 40) / 2
    for i, (t, height) in enumerate(card["lines"]):
        color = colors[t]
        y = L - height
        content = (
            f'<rect x="0" y="{y:.1f}" width="{W}" height="{L - y:.1f}" fill="{color}" opacity=".16"/>'
            f'<line x1="2" y1="{y:.1f}" x2="{W - 2}" y2="{y:.1f}" stroke="{color}" stroke-width="1.6"/>'
            + "".join(f'<circle cx="{cx}" cy="{y:.1f}" r="2.4" fill="{color}" stroke="#0b1a12" stroke-width=".5"/>' for cx in (12, 26, 42, 56))
            + f'<text x="{W / 2}" y="{y - 4:.1f}" font-family="FCA Barlow" font-weight="800" font-size="4.6" fill="#fff" '
            f'text-anchor="middle" stroke="rgba(0,0,0,.7)" stroke-width=".9" paint-order="stroke">{height} m do próprio gol</text>'
        )
        ph = 500
        pw = ph * (W + 8) / (L + 8)
        x = PAD + i * (col + 40) + (col - pw) / 2
        c.parts.append(
            f'<text x="{PAD + i * (col + 40) + col / 2:.1f}" y="{top + 30:.1f}" font-family="FCA Barlow" font-weight="800" '
            f'font-size="40" fill="{color}" text-anchor="middle" letter-spacing="2">{escape(names[t].upper())}</text>'
        )
        svg, _ = pitch_svg(x, top + 52, ph, content)
        c.parts.append(svg)
    c.y = top + 52 + 500
    c.lead(card["lead"], names, colors, size=36)


def _takeaways(c: Canvas, card: dict[str, Any], names: list[str], colors: list[str]) -> None:
    c.title(card["title"])
    c.y += 50
    for i, item in enumerate(card["items"]):
        c.parts.append(f'<text x="{PAD}" y="{c.y + 78:.1f}" font-family="FCA Anton" font-size="96" fill="{colors[0]}">{i + 1}</text>')
        svg, h = text_block(PAD + 120, c.y + 6, item, "inter-500", 38, 52, INNER - 120, names=names, colors=colors)
        c.parts.append(svg)
        c.y += max(h, 96) + 40
    note, h = text_block(PAD, CH - 72 - 40 - 3 * 36, card.get("note") or "", "inter-500", 26, 36, INNER, fill=MUTED, max_lines=3)
    c.parts.append(note)


RENDER = {
    "cover": _cover, "goals": _goals, "bars": _bars, "fullbacks": _fullbacks, "lowblock": _block,
    "buildup": _block, "counts": _counts, "lines": _lines, "takeaways": _takeaways,
}


def _header_right(stats: dict[str, Any]) -> str:
    off = stats.get("official") or {}
    league = (off.get("league") or "").replace("UEFA ", "")
    day = ""
    if off.get("date"):
        try:
            day = datetime.fromisoformat(off["date"].replace("Z", "+00:00")).astimezone().strftime("%d/%m")
        except ValueError:
            day = ""
    if not day:
        started = stats.get("started") or (stats.get("startedAt") or 0) / 1000
        day = time.strftime("%d/%m", time.localtime(started)) if started else ""
    return " · ".join(p for p in (league, day) if p)


def build_cards(stats: dict[str, Any], patterns: dict[str, Any] | None, insights: list[dict[str, Any]] | None = None,
                embed_fonts: bool = True, story: Story | None = None) -> list[str]:
    """Os cards da partida, em SVG (1080 × 1350), na ordem do carrossel."""
    story = story or Story(stats, patterns, insights)
    specs = story.build()
    names = team_names(stats)
    colors = card_colors(stats)
    left = f"{names[0]} x {names[1]}"
    right = _header_right(stats) or "FC Analytics"
    out = []
    for i, spec in enumerate(specs, 1):
        if spec["type"] == "cover":
            canvas = Canvas(i, len(specs), right.split(" · ")[0] if " · " in right else "FC Analytics", right.split(" · ")[-1])
        else:
            canvas = Canvas(i, len(specs), left, right)
        RENDER[spec["type"]](canvas, spec, names, colors)
        if spec["type"] != "takeaways":
            canvas.balance()
        if spec["type"] == "takeaways":
            canvas.footer("Gostou? Salva e manda para quem curte tática")
        else:
            canvas.footer()
        out.append(canvas.svg(embed_fonts))
    return out
