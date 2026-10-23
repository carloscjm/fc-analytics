"""Gera backend/app/assets/fonts/metrics.json: a largura de cada caractere (em frações de em) de cada fonte dos cards.

Os cards do Instagram são SVG, que não quebra linhas sozinho; o backend usa essas larguras para quebrar os
textos no tamanho certo. Rode de novo se trocar alguma fonte. Precisa de: pip install fonttools brotli
Uso (na raiz do repositório): python tools/fonts/metrics.py
"""
import json
from pathlib import Path

from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parents[2] / "backend" / "app" / "assets" / "fonts"
CHARS = [chr(c) for c in range(32, 256)] + list("–—‘’“”•…×→←↑↓·")


def main() -> None:
    out = {}
    for path in sorted(FONTS.glob("*.woff2")):
        font = TTFont(str(path))
        upm = font["head"].unitsPerEm
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]
        widths = {}
        for ch in CHARS:
            glyph = cmap.get(ord(ch))
            if glyph:
                widths[ch] = round(hmtx[glyph][0] / upm, 4)
        out[path.stem] = {"default": round(sum(widths.values()) / max(1, len(widths)), 4), "widths": widths}
    (FONTS / "metrics.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({k: len(v["widths"]) for k, v in out.items()})


if __name__ == "__main__":
    main()
