"""Fotografa todas as telas do painel servido pelo mock.py (Playwright + Chromium).

Uso (na raiz do repositório, com o mock rodando na porta 8765):
    python tools/preview/shoot.py [endereço]
Grava os PNG em tools/preview/out/shots/. O campo 3D precisa de WebGL: o Chromium
roda com SwiftShader (renderização por software).
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "shots"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=ARGS)
        # Sem animação: o campinho troca de etapa a cada 2,5 s, sem esmaecer, e dá para fotografar cada etapa.
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def shot(selector: str, name: str) -> None:
            el = page.locator(selector).first
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            box = el.evaluate(
                "e => { const r = e.getBoundingClientRect();"
                " return {x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height}; }"
            )
            page.screenshot(path=str(OUT / name), full_page=True, clip=box)

        def wait_stage(i: int) -> None:
            page.wait_for_function(
                f"() => {{ const li = document.querySelectorAll('.flow-steps li');"
                f" return li.length === 3 && li[{i}].classList.contains('on'); }}",
                timeout=20000,
            )
            page.wait_for_timeout(150)

        page.goto(URL + "/")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "00-geral.png"), full_page=True)
        tabs = page.locator(".options [role=tab]")
        for i in range(tabs.count()):
            tabs.nth(i).click()
            page.wait_for_timeout(1500)
            shot(".map-card", f"1{i}-campo.png")
            wait_stage(2)
            shot(".flow-card", f"2{i}-movimentacao.png")
        tabs.nth(0).click()
        for s in range(3):
            wait_stage(s)
            shot(".flow-card .flow-wrap", f"3{s}-etapa{s + 1}.png")
        shot(".tactics-card", "40-tatica.png")
        shot(".match-card", "41-estatisticas.png")
        shot(".insights-card", "42-insights.png")
        shot(".topbar", "43-cabecalho.png")
        page.click("text=Finalizar partida")
        page.wait_for_timeout(200)
        shot(".topbar", "44-cabecalho-finalizar.png")
        page.goto(URL + "/report.html")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "50-relatorio.png"), full_page=True)
        browser.close()
    print(f"{len(list(OUT.glob('*.png')))} imagens em {OUT}")
    if errors:
        print("Erros na página:", *errors, sep="\n  ")


if __name__ == "__main__":
    main()
