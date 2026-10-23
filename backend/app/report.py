"""Relatório de uma partida num único arquivo HTML (abre em qualquer navegador e imprime em PDF).

Junta o que o app sabe da partida: placar e eventos marcados, estatísticas da partida
inteira, posse minuto a minuto, formação e posições médias de cada time atacando e
defendendo, leitura tática (posições, saída de bola, jogadas com a bola, mudanças),
movimentação dentro de cada fase, os passes e cruzamentos que mais se repetiram e o
feed de alertas e análises do LLM.
"""

from __future__ import annotations

import colorsys
import time
from html import escape
from typing import Any

from .pitch import LENGTH, WIDTH

DEFAULT_COLORS = ("#2a78d6", "#eb6834")
EVENT_NAMES = {"gol": "Gol", "amarelo": "Cartão amarelo", "vermelho": "Cartão vermelho", "substituicao": "Substituição"}
STATE_NAMES = {"ativa": "em andamento", "pausada": "pausada", "finalizada": "finalizada", "livre": "em andamento"}


def vivid(color: str | None, fallback: str) -> str:
    """Cor da camisa mais forte (mais saturada), para enxergar bem no campo verde.

    Igual à do painel (frontend/src/colors.ts): branco e cinza claro viram quase branco,
    preto e cinza escuro viram grafite; o resto ganha saturação alta e brilho médio.
    """
    if not color or not color.startswith("#") or len(color) != 7:
        return fallback
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.18 or (max(r, g, b) - min(r, g, b)) < 0.08:
        if light >= 0.55:
            return "#f5f7fa"
        if light <= 0.3:
            return "#1f2329"
        return "#9aa3ad"
    sat = max(sat, 0.85)
    light = min(max(light, 0.42), 0.55)
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _mmss(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _num(value: Any, unit: str = "", digits: int = 0) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return escape(str(value))
    text = f"{v:.{digits}f}".replace(".", ",")
    return f"{text}{unit}"


# ---------------------------------------------------------------------------
# Campinhos em SVG
# ---------------------------------------------------------------------------

def _pitch_lines() -> str:
    box_w, box_l, small_w, small_l = 40.32, 16.5, 18.32, 5.5
    parts = [
        f'<rect x="0" y="0" width="{LENGTH}" height="{WIDTH}" />',
        f'<line x1="{LENGTH / 2}" y1="0" x2="{LENGTH / 2}" y2="{WIDTH}" />',
        f'<circle cx="{LENGTH / 2}" cy="{WIDTH / 2}" r="9.15" />',
    ]
    for x, sign in ((0, 1), (LENGTH, -1)):
        for w, l in ((box_w, box_l), (small_w, small_l)):
            x0 = x if sign == 1 else x - l
            parts.append(f'<rect x="{x0}" y="{(WIDTH - w) / 2}" width="{l}" height="{w}" />')
    return "".join(parts)


def pitch_svg(roles: list[dict[str, Any]], color: str, arrows: list[dict[str, Any]] | None = None) -> str:
    """Posições médias de um time (atacando para a direita), com nomes e as setas repetidas."""
    pad = 4
    out = [
        f'<svg class="pitch" viewBox="{-pad} {-pad} {LENGTH + 2 * pad} {WIDTH + 2 * pad}" role="img">',
        '<defs>'
        '<marker id="h-p" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2" markerHeight="2" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#f8fafc"/></marker>'
        '<marker id="h-c" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="2" markerHeight="2" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#fbbf24"/></marker></defs>',
        f'<rect x="{-pad}" y="{-pad}" width="{LENGTH + 2 * pad}" height="{WIDTH + 2 * pad}" fill="#1f4d2b"/>',
        f'<g fill="none" stroke="rgba(255,255,255,.55)" stroke-width=".3">{_pitch_lines()}</g>',
    ]
    for a in arrows or []:
        (x0, y0), (x1, y1) = a["from"], a["to"]
        stroke = "#f8fafc" if a["kind"] == "passe" else "#fbbf24"
        head = "h-p" if a["kind"] == "passe" else "h-c"
        width = 0.9 + min(2.2, a["count"] * 0.18)
        out.append(
            f'<path d="M{x0},{y0} L{x1},{y1}" stroke="{stroke}" stroke-width="{width:.2f}" opacity=".55" '
            f'stroke-linecap="round" marker-end="url(#{head})"/>'
            f'<text x="{(x0 + x1) / 2:.1f}" y="{(y0 + y1) / 2 - 1.6:.1f}" class="arrow-label" fill="{stroke}">{a["count"]}×</text>'
        )
    sector = {0: "#2f7bff"}
    last = max((r["line"] for r in roles), default=0)
    lines: dict[int, list[tuple[float, float]]] = {}
    for r in roles:
        lines.setdefault(r["line"], []).append((r["x"], r["y"]))
    for line, pts in lines.items():
        if len(pts) < 2:
            continue
        color_line = sector.get(line, "#ef4444" if line == last else "#facc15")
        pts.sort(key=lambda p: p[1])
        out.append(
            f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" '
            f'stroke="{color_line}" stroke-width=".45" opacity=".8"/>'
        )
    for r in roles:
        out.append(
            f'<circle cx="{r["x"]:.1f}" cy="{r["y"]:.1f}" r="2" fill="{color}" stroke="#0b130d" stroke-width=".4"/>'
        )
        if r.get("name"):
            out.append(f'<text x="{r["x"]:.1f}" y="{r["y"] - 2.8:.1f}" class="role">{escape(r["name"])}</text>')
    out.append("</svg>")
    return "".join(out)


def possession_svg(minutes: list[int], possession: list[Any], colors: tuple[str, str]) -> str:
    """Posse minuto a minuto: barras empilhadas (time A embaixo, time B em cima)."""
    if not minutes:
        return '<p class="muted">Sem dados de posse.</p>'
    n = len(minutes)
    bar = 600 / max(n, 1)
    out = [f'<svg class="chart" viewBox="0 0 620 130" role="img">']
    out.append('<line x1="10" y1="60" x2="610" y2="60" stroke="#cfd6cc" stroke-dasharray="3 3"/>')
    for i, value in enumerate(possession):
        x = 10 + i * bar
        if not value:
            continue
        a = float(value[0]) / 100
        out.append(f'<rect x="{x:.1f}" y="{10 + (1 - a) * 100:.1f}" width="{max(bar - 1, 0.5):.1f}" height="{a * 100:.1f}" fill="{colors[0]}"/>')
        out.append(f'<rect x="{x:.1f}" y="10" width="{max(bar - 1, 0.5):.1f}" height="{(1 - a) * 100:.1f}" fill="{colors[1]}" opacity=".85"/>')
    step = max(1, n // 10)
    for i in range(0, n, step):
        out.append(f'<text x="{10 + i * bar:.1f}" y="125" class="tick">{minutes[i]}\'</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

CSS = """
:root { --text:#1c2118; --muted:#5d6657; --border:#dde1d8; --bg:#f4f5f1; --card:#fff; }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; color:var(--text); background:var(--bg); }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 28px; margin: 0; }
h2 { font-size: 19px; margin: 28px 0 10px; }
h3 { font-size: 16px; margin: 16px 0 6px; }
.muted { color: var(--muted); }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 12px; }
.score { display:flex; align-items:center; gap:16px; font-size:32px; font-weight:700; margin:14px 0 4px; }
.swatch { display:inline-block; width:14px; height:14px; border-radius:4px; vertical-align:-2px; margin-right:6px; border:1px solid rgba(0,0,0,.2); }
table { width:100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; }
td.n, th.n { text-align: right; }
.grid2 { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 720px) { .grid2 { grid-template-columns: 1fr; } }
svg.pitch { width:100%; height:auto; border-radius:8px; display:block; }
svg.pitch .role { font: 700 2.4px system-ui,sans-serif; fill:#fff; text-anchor:middle; paint-order:stroke; stroke:rgba(0,0,0,.75); stroke-width:.6px; }
svg.pitch .arrow-label { font: 700 2.6px system-ui,sans-serif; text-anchor:middle; paint-order:stroke; stroke:rgba(0,0,0,.8); stroke-width:.6px; }
svg.chart { width:100%; height:auto; }
svg.chart .tick { font: 10px system-ui,sans-serif; fill: var(--muted); }
ul { margin: 4px 0 8px; padding-left: 20px; }
li { margin: 2px 0; }
.insight { border-left: 3px solid var(--border); padding: 4px 0 4px 12px; margin: 10px 0; }
.insight.atencao { border-color: #e0a100; }
.foot { margin-top: 32px; font-size: 13px; }
.source { display:inline-block; font-size:12px; font-weight:600; padding:2px 8px; border-radius:99px; background:#e3efe6; color:#1d5b33; vertical-align:middle; }
.source.warn { background:#fdf0d5; color:#7a5200; }
.summary p { margin: 0 0 10px; }
.summary p:last-child { margin-bottom: 0; }
table.compare td.ours, table.compare th.ours { color: var(--muted); }
.cards { display:grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
@media (max-width: 720px) { .cards { grid-template-columns: 1fr 1fr; } }
.cards figure { margin:0; }
.cards figure > svg { width:100%; height:auto; display:block; border-radius:8px; box-shadow: 0 1px 3px rgba(0,0,0,.18); }
.cards figcaption { display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:13px; }
button.dl { font: inherit; font-size: 13px; font-weight:600; border:1px solid var(--border); background:var(--card); border-radius:8px; padding:5px 10px; cursor:pointer; }
button.dl:hover { border-color: var(--muted); }
@media print { .cards, .cards-actions { display:none; } }
@media print { body { background:#fff; } .card { break-inside: avoid; } }
"""


def _team_header(name: str, color: str) -> str:
    return f'<span class="swatch" style="background:{color}"></span>{escape(name)}'


def _list(items: list[str] | None) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return '<p class="muted">Nada a destacar ainda.</p>'
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def _stats_table(w: dict[str, Any], names: list[str], colors: tuple[str, str]) -> str:
    def pair(key: str, unit: str = "", digits: int = 0) -> tuple[str, str]:
        v = w.get(key) or [None, None]
        return _num(v[0], unit, digits), _num(v[1], unit, digits)

    corridors = w.get("corridors") or [None, None]

    def corr(c: Any) -> str:
        if not c:
            return "—"
        return f"esq. {_num(c[0], '%')} · centro {_num(c[1], '%')} · dir. {_num(c[2], '%')}"

    rows = [
        ("Posse de bola", *pair("possession", "%")),
        ("Domínio territorial (bola no último terço)", *pair("tilt", "%")),
        ("Passes", *pair("passes")),
        ("Perdas de bola", *pair("losses")),
        ("Acerto de passe", *pair("passAccuracy", "%")),
        ("Recupera a bola em até 5 s após perder", *pair("recoveries5s", "%")),
        ("Pressão (jogadores perto da bola após a perda)", *pair("pressure", "", 1)),
        ("Altura média da linha de defesa", *pair("line", " m")),
        ("Largura média do time", *pair("width", " m")),
        ("Profundidade (defesa ao ataque)", *pair("depth", " m")),
        ("Distância percorrida (jogadores vistos)", *pair("distanceKm", " km", 1)),
        ("Corredores do ataque", corr(corridors[0]), corr(corridors[1])),
    ]
    head = (
        f'<tr><th></th><th class="n">{_team_header(names[0], colors[0])}</th>'
        f'<th class="n">{_team_header(names[1], colors[1])}</th></tr>'
    )
    body = "".join(f'<tr><td>{escape(label)}</td><td class="n">{a}</td><td class="n">{b}</td></tr>' for label, a, b in rows)
    return f"<table>{head}{body}</table>"


def _team_section(
    team: int, names: list[str], color: str, patterns: dict[str, Any] | None
) -> str:
    name = names[team]
    options = (patterns or {}).get("options") or {}
    tactics = ((patterns or {}).get("tactics") or {}).get(str(team)) or {}
    flows = (patterns or {}).get("flows") or {}
    arrows = ((patterns or {}).get("ballArrows") or {}).get(str(team)) or []
    transition = ((patterns or {}).get("transitions") or {}).get(str(team)) or {}
    cards = []
    for phase, title, phase_arrows in (("ataque", "atacando", arrows), ("defesa", "defendendo", None)):
        option = options.get(f"{team}-{phase}") or {}
        pattern = option.get("pattern")
        if pattern:
            body = (
                f'<p><strong>{escape(pattern["formation"])}</strong> · linha de defesa a {_num(pattern.get("lineHeight"), " m")} '
                f'do próprio gol (bloco {escape(str(pattern.get("block", "")))}) · largura {_num(pattern.get("width"), " m")} · '
                f'{_mmss(option.get("seconds"))} de jogo analisado</p>'
                + pitch_svg(pattern["roles"], color, phase_arrows)
            )
            flow = flows.get(f"{team}-{phase}")
            if flow:
                stages = " → ".join(escape(s["name"]) for s in flow["stages"])
                body += f'<h3>Movimentação ({stages})</h3>' + _list(flow.get("notes"))
        else:
            body = f'<p class="muted">Poucos momentos do {escape(name)} {title} para montar o padrão '
            body += f'({option.get("frames", 0)} de {option.get("needed", 40)}).</p>'
        cards.append(f'<div class="card"><h3>{escape(name)} {title}</h3>{body}</div>')
    reading = [
        "<h3>Posições</h3>" + _list(tactics.get("positions")),
        "<h3>Saída de bola</h3>" + _list([(tactics.get("buildUp") or {}).get("text")]),
        "<h3>Jogadas com a bola</h3>" + _list((tactics.get("plays") or {}).get("texts")),
        "<h3>Defesa → ataque</h3>" + _list(transition.get("highlights")),
        "<h3>Mudanças nos últimos 10 minutos</h3>" + _list(tactics.get("changes")),
    ]
    return (
        f"<h2>{_team_header(name, color)}</h2>"
        f'<div class="grid2">{"".join(cards)}</div>'
        f'<div class="card">{"".join(reading)}</div>'
    )


def _insights_section(items: list[dict[str, Any]], names: list[str]) -> str:
    if not items:
        return '<p class="muted">Nenhum alerta ou análise nesta partida.</p>'
    out = []
    for item in items:
        who = f" · {escape(names[item['team']])}" if item.get("team") in (0, 1) else ""
        head = f'<p class="muted">{_mmss(item.get("t"))}{who} · {"Análise do LLM" if item.get("kind") == "analise" else "Alerta"}</p>'
        body = f"<p>{escape(item.get('text') or '')}</p>"
        analysis = item.get("analysis")
        if analysis:
            body = f"<p>{escape(analysis.get('leitura') or '')}</p>"
            for key, title in (
                ("funcionando", "O que está funcionando"),
                ("espacos", "Espaços"),
                ("sugestoes", "Sugestões"),
                ("posicoes", "Posições e jogadas"),
            ):
                if analysis.get(key):
                    body += f"<h3>{title}</h3>" + _list(analysis[key])
        out.append(f'<div class="insight {escape(item.get("level") or "")}">{head}{body}</div>')
    return "".join(out)


def _official_section(story: Any, names: list[str], pal: tuple[str, str]) -> str:
    off = story.off
    if not off:
        return (
            '<h2>Dados oficiais</h2><div class="card"><p><span class="source warn">Não conferido</span> '
            "O placar e as contagens abaixo vêm só da análise por vídeo. Para usar os dados oficiais, finalize a partida "
            "pelo painel e confirme o jogo na lista.</p></div>"
        )
    goals = off.get("goals") or []
    goal_rows = "".join(
        f"<tr><td>{escape(g.get('minute') or '')}</td><td>{_team_header(names[g['team']], pal[g['team']]) if g.get('team') in (0, 1) else ''}</td>"
        f"<td>{escape(g.get('player') or '')}{' (pênalti)' if g.get('penalty') else ''}{' (gol contra)' if g.get('ownGoal') else ''}</td>"
        f"<td class=\"muted\">{escape(g.get('assist') or '')}</td></tr>"
        for g in goals
    )
    cards = off.get("cards") or []
    card_rows = "".join(
        f"<tr><td>{escape(c.get('minute') or '')}</td><td>{_team_header(names[c['team']], pal[c['team']]) if c.get('team') in (0, 1) else ''}</td>"
        f"<td>{escape(c.get('player') or '')}</td><td>{escape(c.get('kind') or '')}</td></tr>"
        for c in cards
    )
    head = (
        f'<tr><th></th><th class="n">{_team_header(names[0], pal[0])}</th><th class="n">{_team_header(names[1], pal[1])}</th>'
        f'<th class="n ours">{escape(names[0])} (vídeo)</th><th class="n ours">{escape(names[1])} (vídeo)</th></tr>'
    )
    rows = "".join(
        f'<tr><td>{escape(label)}</td><td class="n">{a}</td><td class="n">{b}</td><td class="n ours">{c}</td><td class="n ours">{d}</td></tr>'
        for label, a, b, c, d in story.comparison()
    )
    place = " · ".join(p for p in (off.get("league"), off.get("venue")) if p)
    return f"""<h2>Dados oficiais <span class="source">Fonte: {escape(off.get("source") or "")}</span></h2>
<div class="card">
<p class="muted">{escape(place)}</p>
<h3>Gols</h3>
{f'<table><tr><th>Minuto</th><th>Time</th><th>Autor</th><th>Assistência</th></tr>{goal_rows}</table>' if goals else '<p class="muted">Sem gols.</p>'}
{f'<h3>Cartões</h3><table><tr><th>Minuto</th><th>Time</th><th>Jogador</th><th>Cartão</th></tr>{card_rows}</table>' if cards else ''}
<h3>Oficial × o que a câmera mediu</h3>
<table class="compare">{head}{rows}</table>
<p class="muted">A câmera só conta o que aparece na transmissão ({story.minutes} minutos analisados), por isso as contagens
de passes, finalizações e cruzamentos ficam abaixo das oficiais. No relatório e nos cards valem os números oficiais;
a análise por vídeo entra na parte tática (formação, linhas, laterais, saída de bola).</p>
</div>"""


CARDS_JS = """
(function () {
  var fonts = document.getElementById('fca-fonts').textContent;
  var slug = document.body.getAttribute('data-slug') || 'partida';
  function png(svg) {
    var clone = svg.cloneNode(true);
    var style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent = fonts;
    clone.insertBefore(style, clone.firstChild);
    clone.setAttribute('width', '1080');
    clone.setAttribute('height', '1350');
    var xml = new XMLSerializer().serializeToString(clone);
    var img = new Image();
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
    return img.decode().then(function () {
      return new Promise(function (ok) { setTimeout(ok, 150); });
    }).then(function () {
      var canvas = document.createElement('canvas');
      canvas.width = 1080; canvas.height = 1350;
      canvas.getContext('2d').drawImage(img, 0, 0, 1080, 1350);
      return new Promise(function (ok) { canvas.toBlob(ok, 'image/png'); });
    });
  }
  function save(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }
  function one(i) {
    var svg = document.querySelector('#card-' + i + ' svg');
    return png(svg).then(function (blob) { save(blob, slug + '-card-' + String(i).padStart(2, '0') + '.png'); });
  }
  document.querySelectorAll('button[data-card]').forEach(function (b) {
    b.addEventListener('click', function () { one(Number(b.getAttribute('data-card'))); });
  });
  var all = document.getElementById('cards-all');
  if (all) all.addEventListener('click', function () {
    var n = document.querySelectorAll('.cards figure').length, chain = Promise.resolve();
    for (var i = 1; i <= n; i++) (function (k) { chain = chain.then(function () { return one(k); }); })(i);
  });
})();
"""


def _slug(text: str) -> str:
    import re
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60] or "partida"


def build_report(
    stats: dict[str, Any],
    patterns: dict[str, Any] | None,
    insights: list[dict[str, Any]],
    colors: list[str] | None,
    version: str,
) -> str:
    from .cards import build_cards, font_css
    from .story import Story, team_names

    story = Story(stats, patterns, insights)
    names = team_names(stats)
    pal = (
        vivid((colors or [None, None])[0], DEFAULT_COLORS[0]),
        vivid((colors or [None, None])[1], DEFAULT_COLORS[1]),
    )
    title = stats.get("matchName") or f"{names[0]} x {names[1]}"
    started_s = (stats.get("startedAt") or 0) / 1000
    when = time.strftime("%d/%m/%Y às %H:%M", time.localtime(started_s)) if started_s else "Data não registrada"
    state = STATE_NAMES.get(stats.get("matchState") or "", "")
    score = story.score or stats.get("score") or [0, 0]
    score_note = (
        f'<span class="source">Placar oficial · {escape(story.off.get("source") or "")}</span>' if story.off
        else '<span class="source warn">Placar marcado no app (não conferido)</span>'
    )
    summary_html = "".join(f"<p>{escape(p)}</p>" for p in story.summary())
    card_svgs = build_cards(stats, patterns, insights, embed_fonts=False, story=story)
    cards_html = "".join(
        f'<figure id="card-{i}">{svg}<figcaption><span class="muted">{i}/{len(card_svgs)}</span>'
        f'<button class="dl" data-card="{i}">Baixar imagem</button></figcaption></figure>'
        for i, svg in enumerate(card_svgs, 1)
    )
    whole = (stats.get("windows") or {}).get("partida") or {}

    events = [e for e in stats.get("events") or [] if e.get("kind") != "intervalo"]
    breaks = [e for e in stats.get("events") or [] if e.get("kind") == "intervalo"]
    event_rows = "".join(
        f"<tr><td>{_mmss(e['t'])}</td><td>{escape(EVENT_NAMES.get(e['kind'], e['kind']))}</td>"
        f"<td>{escape(names[e['team']]) if e.get('team') in (0, 1) else ''}</td></tr>"
        for e in events
    )
    events_html = (
        f"<table><tr><th>Tempo</th><th>Evento</th><th>Time</th></tr>{event_rows}</table>"
        if events
        else '<p class="muted">Nenhum evento marcado.</p>'
    )
    pauses = stats.get("pauses") or []
    pauses_html = (
        "<ul>" + "".join(f"<li>Aos {_mmss(at)}, por {_mmss(dur)}</li>" for at, dur in pauses) + "</ul>"
        if pauses
        else ""
    )
    if breaks:
        pauses_html += f'<p class="muted">Intervalo marcado {len(breaks)} vez(es).</p>'

    timeline = stats.get("timeline") or {}
    generated = time.strftime("%d/%m/%Y %H:%M")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Relatório FC Analytics</title>
<style>{CSS}</style>
<style id="fca-fonts">{font_css(True)}</style>
</head>
<body data-slug="{escape(_slug(title))}">
<main>
<p class="muted">Relatório FC Analytics · partida {escape(state)}</p>
<h1>{escape(title)}</h1>
<p class="muted">{when} · {_mmss(stats.get("elapsedS"))} de jogo analisado (sem contar as pausas)</p>
<div class="score">{_team_header(names[0], pal[0])} {score[0]} × {score[1]} {_team_header(names[1], pal[1])}</div>
<p>{score_note}</p>

<h2>Resumo final</h2>
<div class="card summary">{summary_html or '<p class="muted">Pouco jogo analisado para um resumo.</p>'}</div>

{_official_section(story, names, pal)}

<h2>Eventos marcados no app</h2>
<div class="card">{events_html}{('<h3>Pausas da captura</h3>' + pauses_html) if pauses_html else ''}</div>

<h2>Estatísticas da partida</h2>
<div class="card">{_stats_table(whole, names, pal)}</div>

<h2>Posse minuto a minuto</h2>
<div class="card">
<p class="muted">{_team_header(names[0], pal[0])} embaixo · {_team_header(names[1], pal[1])} em cima · minutos sem bola visível ficam vazios</p>
{possession_svg(timeline.get("minutes") or [], timeline.get("possession") or [], pal)}
</div>

{_team_section(0, names, pal[0], patterns)}
{_team_section(1, names, pal[1], patterns)}

<h2>Alertas e análises</h2>
<div class="card">{_insights_section(insights, names)}</div>

<h2>Cards para o Instagram</h2>
<div class="card">
<p class="muted cards-actions">Carrossel vertical (1080 × 1350) com o resumo da partida, para postar como está.
<button class="dl" id="cards-all">Baixar todos</button></p>
<div class="cards">{cards_html}</div>
</div>

<p class="foot muted">
Gerado pelo FC Analytics {escape(version)} em {generated}. Os números vêm do que a câmera da transmissão mostrou:
posições são médias de quem ocupa cada região, a posse só conta quando a bola aparece, e passes e cruzamentos
dependem de a bola estar visível. Nos campinhos, o time ataca da esquerda para a direita; setas brancas são os passes
que mais se repetiram e as amarelas, os cruzamentos.
</p>
</main>
<script>{CARDS_JS}</script>
</body>
</html>
"""
