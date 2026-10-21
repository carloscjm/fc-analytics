"""Leitura tática: como cada posição se comporta, saída de bola, jogadas com a bola e mudanças no jogo.

Tudo aqui trabalha com o time atacando para a direita (próprio gol em x = 0) e
com o lado esquerdo do time em y pequeno, como nos padrões.

- **Posições:** a partir das posições médias com nome (LE, VOL, MEI, PE, CA...),
  descreve se o lateral apoia por fora ou por dentro, se o ponta abre ou fecha,
  se o volante recua entre os zagueiros, onde os meias jogam e o que faz o
  centroavante.
- **Saída de bola:** quando o time tem a bola no próprio terço e a câmera mostra a
  largura do campo na altura da defesa, conta quem forma a última linha e
  classifica: 2 zagueiros, 3 com o volante entre os zagueiros, 3 com um lateral
  que fica, 4 atrás.
- **Jogadas com a bola:** pelo caminho da bola (só quando ela foi vista de fato),
  conta cruzamentos para a área, entradas na área com a bola dominada, chutes de
  fora e de dentro da área, e conduções pelos lados que cortam para dentro ou vão
  ao fundo.
- **Mudanças:** compara os últimos 10 minutos com o que veio antes.

As contagens dependem de a bola aparecer na imagem: são aproximadas.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from .pitch import LENGTH, WIDTH

RECENT_S = 600.0  # "últimos 10 minutos"

BOX_X = LENGTH - 16.5
BOX_Y0, BOX_Y1 = WIDTH / 2 - 20.16, WIDTH / 2 + 20.16
GOAL_Y0, GOAL_Y1 = WIDTH / 2 - 3.66, WIDTH / 2 + 3.66
WIDE_Y = 18.0  # corredor lateral: até 18 m da linha lateral

LEFT_ROLES = {"LE", "ALE", "PE", "ME"}
RIGHT_ROLES = {"LD", "ALD", "PD", "MD"}
FULLBACKS = {"LE", "LD", "ALE", "ALD"}
WINGERS = {"PE", "PD"}
MIDS = {"MC", "MEI", "ME", "MD"}

ROLE_WORDS = {
    "LE": "lateral esquerdo", "LD": "lateral direito", "ALE": "ala esquerdo", "ALD": "ala direito",
    "PE": "ponta esquerdo", "PD": "ponta direito", "VOL": "volante", "MC": "meia central",
    "MEI": "meia", "ME": "meia pela esquerda", "MD": "meia pela direita", "CA": "centroavante", "ZAG": "zagueiro",
}


def _times(n: int) -> str:
    return f"{n} vez" if n == 1 else f"{n} vezes"


def in_box(x: float, y: float) -> bool:
    return x >= BOX_X and BOX_Y0 <= y <= BOX_Y1


def side_distance(name: str, y: float) -> float:
    """Distância até a linha lateral do lado da posição."""
    return y if name in LEFT_ROLES else WIDTH - y


def lane(dist: float) -> str:
    if dist <= 10:
        return "por fora, colado na linha lateral"
    if dist >= 17:
        return "por dentro, mais perto do meio"
    return "entre a lateral e o meio"


# ---------------------------------------------------------------------------
# Saída de bola
# ---------------------------------------------------------------------------


def classify_build_up(line: np.ndarray) -> str | None:
    """Quem forma a última linha na saída de bola (posições normalizadas dos jogadores dessa linha)."""
    n = len(line)
    if n == 2:
        return "2 zagueiros (laterais adiantados)"
    if n == 4:
        return "4 atrás"
    if n >= 5:
        return "5 atrás"
    if n != 3:
        return None
    ys = np.sort(line[:, 1])
    wide_left = ys[0] < 14
    wide_right = ys[2] > WIDTH - 14
    if wide_right and not wide_left:
        return "3, com o lateral direito ficando"
    if wide_left and not wide_right:
        return "3, com o lateral esquerdo ficando"
    if not wide_left and not wide_right and abs(ys[1] - WIDTH / 2) <= 8:
        return "3, com o volante entre os zagueiros"
    return "3 atrás"


def build_up_summary(entries: list[tuple[float, str]], since: float | None = None) -> dict[str, Any]:
    values = [label for wall, label in entries if since is None or wall >= since]
    tally = Counter(values)
    total = len(values)
    top = tally.most_common(1)[0] if tally else None
    return {
        "counts": dict(tally.most_common()),
        "total": total,
        "main": top[0] if top and total >= 15 and top[1] / total >= 0.4 else None,
        "share": round(top[1] / total, 2) if top else 0.0,
    }


def build_up_text(info: dict[str, Any]) -> str | None:
    if not info["total"]:
        return None
    if info["main"] is None:
        parts = ", ".join(f"{k} ({v})" for k, v in list(info["counts"].items())[:3])
        return f"Saída de bola variada ou ainda com poucos lances ({info['total']}): {parts}."
    return f"Saída de bola com {info['main']} em {round(100 * info['share'])}% de {info['total']} lances."


# ---------------------------------------------------------------------------
# Jogadas com a bola
# ---------------------------------------------------------------------------

PLAY_KINDS = ("cruzamento", "entrada", "chute_fora", "chute_dentro", "corta_dentro", "vai_fundo")
PLAY_WORDS = {
    "cruzamento": "cruzamentos para a área",
    "entrada": "entradas na área com a bola dominada",
    "chute_fora": "chutes de fora da área",
    "chute_dentro": "chutes de dentro da área",
    "corta_dentro": "conduções pelo lado que cortam para dentro",
    "vai_fundo": "conduções pelo lado que vão ao fundo",
}


@dataclass
class BallPoint:
    wall: float
    x: float
    y: float


class BallPlays:
    """Detecta jogadas pelo caminho da bola do time que tem a posse (coordenadas já normalizadas)."""

    CROSS_WINDOW_S = 1.8
    SHOT_SPEED = 18.0
    CARRY_MIN_S = 1.5

    def __init__(self) -> None:
        self.events: deque[tuple[float, int, str, str | None]] = deque(maxlen=6000)
        self.reset_path()

    def reset_path(self) -> None:
        self.team: int | None = None
        self.path: deque[BallPoint] = deque(maxlen=40)
        self.cooldown: dict[str, float] = {}
        self.carry: BallPoint | None = None

    def _emit(self, wall: float, kind: str, side: str | None, cooldown: float) -> None:
        key = f"{kind}:{side}"
        if wall - self.cooldown.get(key, -1e9) < cooldown:
            return
        self.cooldown[key] = wall
        if kind in ("cruzamento", "entrada"):
            self.cooldown["cruzamento:None"] = self.cooldown["entrada:None"] = wall
        self.events.append((wall, int(self.team), kind, side))

    def add(self, wall: float, team: int | None, x: float | None, y: float | None) -> None:
        """Um ponto da bola vista de fato, com o time que tem a posse (ou None para quebrar a sequência)."""
        if team is None or x is None or y is None:
            self.reset_path()
            return
        if team != self.team or (self.path and wall - self.path[-1].wall > 0.8):
            self.reset_path()
            self.team = team
        point = BallPoint(wall, float(x), float(y))
        prev = self.path[-1] if self.path else None
        self.path.append(point)
        if prev is None:
            return

        # Chute: bola rápida indo na direção do gol.
        dt = max(point.wall - prev.wall, 1e-3)
        vx, vy = (point.x - prev.x) / dt, (point.y - prev.y) / dt
        # (Vinda da faixa lateral em diagonal é cruzamento, não chute.)
        central = 10 <= prev.y <= WIDTH - 10 and abs(vy) <= 0.7 * vx
        if vx > 0 and central and np.hypot(vx, vy) >= self.SHOT_SPEED and prev.x >= 60:
            y_goal = prev.y + vy / vx * (LENGTH - prev.x)
            if GOAL_Y0 - 5 <= y_goal <= GOAL_Y1 + 5:
                kind = "chute_dentro" if in_box(prev.x, prev.y) else "chute_fora"
                self._emit(point.wall, kind, None, 3.0)

        # Cruzamento: da faixa lateral do último terço para dentro da área em pouco tempo.
        if in_box(point.x, point.y) and not in_box(prev.x, prev.y):
            crossed = False
            for p in self.path:
                if point.wall - p.wall > self.CROSS_WINDOW_S:
                    continue
                wide = p.y <= WIDE_Y or p.y >= WIDTH - WIDE_Y
                if p.x >= 70 and wide and np.hypot(point.x - p.x, point.y - p.y) >= 12:
                    self._emit(point.wall, "cruzamento", "esquerda" if p.y < WIDTH / 2 else "direita", 4.0)
                    crossed = True
                    break
            if not crossed:
                self._emit(point.wall, "entrada", None, 4.0)

        # Condução pelo lado no último terço: corta para dentro ou vai ao fundo.
        wide_now = point.x >= 62 and (point.y <= WIDE_Y or point.y >= WIDTH - WIDE_Y)
        if self.carry is None:
            if wide_now:
                self.carry = point
            return
        start = self.carry
        if point.wall - start.wall < self.CARRY_MIN_S:
            return
        side = "esquerda" if start.y < WIDTH / 2 else "direita"
        inward = abs(start.y - WIDTH / 2) - abs(point.y - WIDTH / 2)
        if inward >= 7:
            self._emit(point.wall, "corta_dentro", side, 5.0)
        elif point.x - start.x >= 8 and (point.y <= WIDE_Y or point.y >= WIDTH - WIDE_Y):
            self._emit(point.wall, "vai_fundo", side, 5.0)
        self.carry = point if wide_now else None


def plays_summary(events: list[tuple[float, int, str, str | None]], team: int, since: float | None = None) -> dict[str, Any]:
    mine = [e for e in events if e[1] == team and (since is None or e[0] >= since)]
    counts = {k: sum(1 for e in mine if e[2] == k) for k in PLAY_KINDS}
    by_side = {
        k: {s: sum(1 for e in mine if e[2] == k and e[3] == s) for s in ("esquerda", "direita")}
        for k in ("cruzamento", "corta_dentro", "vai_fundo")
    }
    return {"counts": counts, "bySide": by_side}


def plays_texts(whole: dict[str, Any], recent: dict[str, Any]) -> list[str]:
    c, r = whole["counts"], recent["counts"]
    out = []
    crosses, entries = c["cruzamento"], c["entrada"]
    if crosses + entries >= 4:
        if crosses >= 2 * max(entries, 1):
            out.append(f"Chega à área mais no cruzamento (chuveirinho): {crosses} cruzamentos contra {entries} entradas com a bola dominada.")
        elif entries >= 2 * max(crosses, 1):
            out.append(f"Prefere trabalhar a bola até entrar na área: {entries} entradas com a bola dominada contra {crosses} cruzamentos.")
        else:
            out.append(f"Mistura cruzamentos ({crosses}) e entradas trabalhadas na área ({entries}).")
    shots_out, shots_in = c["chute_fora"], c["chute_dentro"]
    if shots_out + shots_in >= 3:
        if shots_out > shots_in:
            out.append(f"Arrisca muito de fora: {shots_out} chutes de fora da área e {shots_in} de dentro.")
        else:
            out.append(f"Finaliza mais de perto: {shots_in} chutes de dentro da área e {shots_out} de fora.")
    for side in ("esquerda", "direita"):
        inside = whole["bySide"]["corta_dentro"][side]
        deep = whole["bySide"]["vai_fundo"][side]
        if inside + deep >= 3:
            if inside > deep:
                out.append(f"Pela {side}, a jogada costuma cortar para dentro ({_times(inside)}) mais do que ir ao fundo ({deep}).")
            else:
                out.append(f"Pela {side}, a jogada costuma ir ao fundo ({_times(deep)}) mais do que cortar para dentro ({inside}).")
    if r["cruzamento"] >= 4 and r["cruzamento"] >= 2 * max(r["entrada"], 1):
        out.append(f"Nos últimos 10 minutos: {r['cruzamento']} cruzamentos na área.")
    return out


# ---------------------------------------------------------------------------
# Comportamento de cada posição
# ---------------------------------------------------------------------------


def _by_name(roles: list[dict[str, Any]], names: set[str]) -> list[dict[str, Any]]:
    return [r for r in roles if r.get("name") in names]


def role_texts(attack: dict[str, Any] | None, defense: dict[str, Any] | None, plays: dict[str, Any] | None) -> list[str]:
    """Frases sobre cada posição, com o time atacando (e a forma de defender)."""
    out: list[str] = []
    if defense:
        back = int(str(defense["formation"]).split("-")[0])
        out.append(f"Defende com {back} atrás, com a linha a {defense['lineHeight']:.0f} m do próprio gol ({defense['formation']}).")
    if not attack:
        return out
    roles = attack["roles"]
    by_name = {}
    for r in roles:
        by_name.setdefault(r.get("name", ""), []).append(r)
    back_x = float(np.mean([r["x"] for r in roles if r["line"] == 0])) if any(r["line"] == 0 for r in roles) else 0.0

    # Laterais e alas, e a relação com o ponta do mesmo lado.
    for fb in _by_name(roles, FULLBACKS):
        name = fb["name"]
        dist = side_distance(name, fb["y"])
        height = "sobe e apoia" if fb["x"] >= 55 else ("avança até o meio-campo" if fb["x"] >= 42 else "fica mais atrás")
        text = f"{name} ({ROLE_WORDS[name]}): {height} ({fb['x']:.0f} m do próprio gol), {lane(dist)} ({dist:.0f} m da linha lateral)"
        winger = next(iter(_by_name(roles, {"PE" if name in LEFT_ROLES else "PD"})), None)
        if winger:
            wdist = side_distance(winger["name"], winger["y"])
            if wdist >= dist + 4 and winger["x"] - fb["x"] <= 15:
                text += f"; passa por fora do {winger['name']}, que fecha para o meio"
            elif dist >= wdist + 4:
                text += f"; o {winger['name']} fica mais aberto que ele"
        out.append(text + ".")

    # Pontas.
    for w in _by_name(roles, WINGERS):
        name = w["name"]
        dist = side_distance(name, w["y"])
        how = "aberto, dando amplitude" if dist <= 8 else ("por dentro, perto da área" if dist >= 15 else "entre a ponta e o meio")
        text = f"{name} ({ROLE_WORDS[name]}): joga {how} ({dist:.0f} m da linha lateral)"
        if plays:
            side = "esquerda" if name in LEFT_ROLES else "direita"
            inside = plays["bySide"]["corta_dentro"][side]
            deep = plays["bySide"]["vai_fundo"][side]
            if inside + deep >= 2:
                text += f"; pelo lado dele, a jogada corta para dentro {_times(inside)} e vai ao fundo {_times(deep)}"
        out.append(text + ".")

    # Volantes.
    vols = sorted(_by_name(roles, {"VOL"}), key=lambda r: r["x"])
    for v in vols:
        if v["x"] - back_x <= 6 and abs(v["y"] - WIDTH / 2) <= 12:
            out.append(f"VOL (volante): recua para a altura dos zagueiros quando o time tem a bola ({v['x']:.0f} m), ajudando na saída.")
            break
    if len(vols) >= 2 and vols[-1]["x"] - vols[0]["x"] >= 8:
        out.append(f"Volantes: um segura ({vols[0]['x']:.0f} m) e o outro chega mais à frente ({vols[-1]['x']:.0f} m).")
    elif len(vols) >= 2:
        out.append(f"Volantes: jogam lado a lado, na mesma altura ({np.mean([v['x'] for v in vols]):.0f} m).")

    # Meias.
    ca = max(_by_name(roles, {"CA"}), key=lambda r: r["x"], default=None)
    mids = _by_name(roles, MIDS)
    for m in mids:
        name = m["name"]
        if ca and m["x"] >= ca["x"] - 16 and abs(m["y"] - WIDTH / 2) <= 12:
            where = "entre as linhas, logo atrás do centroavante"
        elif m["y"] <= 14 or m["y"] >= WIDTH - 14:
            where = "aberto, pelo lado"
        elif vols and m["x"] - max(v["x"] for v in vols) <= 6:
            where = "recuado, perto dos volantes, ajudando a construir"
        else:
            where = "pelo meio, na intermediária"
        out.append(f"{name} ({ROLE_WORDS[name]}): joga {where} ({m['x']:.0f} m do próprio gol).")
    if len(mids) >= 2:
        spread = max(m["y"] for m in mids) - min(m["y"] for m in mids)
        out.append(f"Meio-campo: {'aberto, ocupando a largura' if spread >= 35 else 'compacto, por dentro'} ({spread:.0f} m entre os meias mais distantes).")

    # Centroavante.
    if ca:
        others = [r for r in roles if r is not ca]
        top_other = max((r["x"] for r in others), default=0.0)
        if ca["x"] >= top_other and abs(ca["y"] - WIDTH / 2) <= 9:
            how = "fica na referência, à frente de todos e pelo meio"
        elif ca["x"] < top_other - 5:
            how = "recua para buscar o jogo (os pontas ficam mais à frente)"
        else:
            how = "se movimenta pelos lados"
        out.append(f"CA (centroavante): {how} ({ca['x']:.0f} m do próprio gol).")
    return out


# ---------------------------------------------------------------------------
# Mudanças: últimos 10 minutos contra antes
# ---------------------------------------------------------------------------


def match_to_reference(roles: list[dict[str, Any]], reference: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Liga as posições de uma janela às posições de referência (que têm os nomes)."""
    from scipy.optimize import linear_sum_assignment

    cost = np.array([[np.hypot(a["x"] - b["x"], a["y"] - b["y"]) for b in reference] for a in roles])
    rows, cols = linear_sum_assignment(cost)
    return {int(j): roles[int(i)] for i, j in zip(rows, cols)}


def change_texts(
    reference: dict[str, Any] | None,
    earlier: dict[str, Any] | None,
    recent: dict[str, Any] | None,
    back_earlier: int | None,
    back_recent: int | None,
    build_earlier: str | None,
    build_recent: str | None,
) -> list[str]:
    out: list[str] = []
    if back_earlier and back_recent and back_earlier != back_recent:
        out.append(f"Passou a defender com {back_recent} atrás (antes eram {back_earlier}).")
    if build_earlier and build_recent and build_earlier != build_recent:
        out.append(f"Na saída de bola, passou de {build_earlier} para {build_recent}.")
    if reference and earlier and recent:
        ref = reference["roles"]
        e = match_to_reference(earlier["roles"], ref)
        r = match_to_reference(recent["roles"], ref)
        for j, role in enumerate(ref):
            name = role.get("name", "")
            if j not in e or j not in r or not name:
                continue
            a, b = e[j], r[j]
            if name in LEFT_ROLES | RIGHT_ROLES:
                da, db = side_distance(name, a["y"]), side_distance(name, b["y"])
                if abs(db - da) >= 7:
                    out.append(f"{name}: antes jogava {lane(da)}, agora {lane(db)} ({da:.0f} → {db:.0f} m da linha lateral).")
                    continue
            dx = b["x"] - a["x"]
            if abs(dx) >= 10:
                out.append(f"{name}: passou a jogar {abs(dx):.0f} m mais {'adiantado' if dx > 0 else 'recuado'}.")
    return out[:6]
