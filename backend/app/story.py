"""A "história" da partida para o relatório final e os cards do Instagram.

Junta os dados oficiais (placar, gols, posse, finalizações, cruzamentos, quando a
pessoa confirmou o jogo na fonte pública) com o que a análise por vídeo mediu
(formação, laterais, linha de defesa, saída de bola, movimentação) e escolhe,
por regras, o que vale contar. Os textos são montados aqui, com os números
certos; nada é inventado e nada depende do LLM.

Regra de escrita: o nome do time vem sem artigo ("Arsenal teve mais a bola"),
porque o gênero muda de time para time ("o Bayern", "a Juventus").
"""

from __future__ import annotations

from typing import Any

from .flows import back_line

ROLE_WORDS = {
    "LE": "lateral esquerdo", "LD": "lateral direito", "ALE": "ala esquerdo", "ALD": "ala direito",
    "VOL": "volante", "MC": "meio-campista", "ME": "meia pela esquerda", "MD": "meia pela direita",
    "MEI": "meia", "PE": "ponta esquerda", "PD": "ponta direita", "CA": "centroavante", "ZAG": "zagueiro",
}
FULLBACKS = ("LE", "LD", "ALE", "ALD")


def _n(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    text = f"{value:.{digits}f}"
    return text.replace(".", ",")


def _pct_pair(a: float | None, b: float | None) -> tuple[int, int] | None:
    if a is None or b is None or a + b <= 0:
        return None
    pa = round(100 * a / (a + b))
    return pa, 100 - pa


def team_names(stats: dict[str, Any]) -> list[str]:
    """Nomes para mostrar: os oficiais (curtos) quando o jogo foi conferido, senão as siglas do placar."""
    off = stats.get("official")
    if off and len(off.get("teams") or []) == 2:
        return [t.get("short") or t.get("name") or "Time" for t in off["teams"]]
    names = stats.get("teamNames") or ["Time A", "Time B"]
    return [str(names[0]), str(names[1])]


def _official_stat(off: dict[str, Any] | None, key: str) -> list[float | None]:
    if not off:
        return [None, None]
    return [(t.get("stats") or {}).get(key) for t in off["teams"]]


def _goal_story(goals: list[dict[str, Any]], names: list[str], score: list[int]) -> str:
    if not goals:
        return "Nenhum gol no jogo."
    a = b = 0
    parts = []
    leader = None
    for i, g in enumerate(goals):
        t = g.get("team")
        if t not in (0, 1):
            continue
        if t == 0:
            a += 1
        else:
            b += 1
        minute = g.get("minute") or ""
        new_leader = 0 if a > b else (1 if b > a else None)
        if i == 0:
            parts.append(f"{names[t]} saiu na frente aos {minute}")
        elif new_leader is None:
            parts.append(f"{names[t]} empatou aos {minute}")
        elif leader is None and new_leader == t and i > 1:
            parts.append(f"{names[t]} virou aos {minute}")
        elif new_leader == t and leader == t:
            parts.append(f"{names[t]} ampliou aos {minute}")
        else:
            parts.append(f"{names[t]} descontou aos {minute}")
        leader = new_leader
    text = ", ".join(parts[:-1]) + (" e " if len(parts) > 1 else "") + parts[-1] + "."
    return text[0].upper() + text[1:]


class Story:
    """Escolhe e escreve o que contar. `cards` é a lista de cards; `report` alimenta o relatório."""

    def __init__(self, stats: dict[str, Any], patterns: dict[str, Any] | None, insights: list[dict[str, Any]] | None = None):
        self.stats = stats
        self.patterns = patterns or {}
        self.insights = insights or []
        self.off = stats.get("official") if stats.get("official") and len(stats["official"].get("teams") or []) == 2 else None
        self.names = team_names(stats)
        self.whole = (stats.get("windows") or {}).get("partida") or {}
        self.minutes = int((stats.get("elapsedS") or 0) // 60)

    # ---------- números ----------

    @property
    def score(self) -> list[int] | None:
        if self.off:
            return [int(t.get("score") or 0) for t in self.off["teams"]]
        goals = [e for e in self.stats.get("events") or [] if e.get("kind") == "gol"]
        return list(self.stats.get("score") or [0, 0]) if goals else None

    @property
    def possession(self) -> list[float | None]:
        off = _official_stat(self.off, "posse")
        if off[0] is not None:
            return off
        return list(self.whole.get("possession") or [None, None])

    def option(self, team: int, phase: str) -> dict[str, Any] | None:
        return ((self.patterns.get("options") or {}).get(f"{team}-{phase}") or {}).get("pattern")

    def flow(self, team: int, phase: str) -> dict[str, Any] | None:
        return (self.patterns.get("flows") or {}).get(f"{team}-{phase}")

    def tactics(self, team: int) -> dict[str, Any]:
        return (self.patterns.get("tactics") or {}).get(str(team)) or {}

    def line_height(self, team: int) -> float | None:
        values = self.whole.get("line") or [None, None]
        return values[team]

    # ---------- candidatos a destaque tático de cada time ----------

    def fullbacks(self, t: int) -> dict[str, Any] | None:
        tr = (self.patterns.get("transitions") or {}).get(str(t)) or {}
        attack = self.option(t, "ataque")
        moves = [m for m in tr.get("moves") or [] if m.get("name") in FULLBACKS and m.get("dx", 0) >= 15]
        if not moves or not attack:
            return None
        moves.sort(key=lambda m: -m["dx"])
        top = moves[0]
        if top["dx"] < 20:
            return None
        flow = self.flow(t, "ataque")
        staying = len(back_line(flow["stages"][-1]["roles"])) if flow else None
        name = self.names[t]
        who = ROLE_WORDS[top["name"]]
        outside = any("passa por fora" in p and p.startswith(top["name"]) for p in self.tactics(t).get("positions") or [])
        lead = f"Quando {name} tinha a bola, o {who} subia {round(top['dx'])} metros e virava quase um ponta"
        lead += ", passando por fora do ponta, que fechava para o meio." if outside else "."
        if len(moves) > 1:
            lead += f" O {ROLE_WORDS[moves[1]['name']]} também subia, {round(moves[1]['dx'])} metros."
        big = [(f"{round(top['dx'])} m", f"é quanto o {who} sobe quando o time ataca")]
        if staying and staying <= 3:
            big.append((str(staying), f"{'jogadores ficam' if staying > 1 else 'jogador fica'} atrás. O resto vai para o ataque"))
        title = f"{name}: laterais viram atacantes" if len(moves) > 1 else f"{name}: o {who} vira atacante"
        return {
            "type": "fullbacks", "team": t, "score": top["dx"], "title": title, "lead": lead, "big": big,
            "roles": attack["roles"], "moves": [{"name": m["name"], "from": m["from"], "to": m["to"]} for m in moves[:2]],
            "takeaway": f"{name} atacou com os laterais subindo como pontas.",
        }

    def low_block(self, t: int) -> dict[str, Any] | None:
        flow = self.flow(t, "defesa")
        defense = self.option(t, "defesa")
        if not flow or not defense:
            return None
        first, last = flow["stages"][0]["roles"], flow["stages"][-1]["roles"]
        members = back_line(last)
        if len(members) < 5:
            return None
        extra = [m for m in members if m.get("line", 0) > 0 and not m.get("estimated")]
        name = self.names[t]
        line = round(defense.get("lineHeight") or 0)
        lead = f"Sem a bola, {name} defendeu com a linha a {line} metros do próprio gol."
        if extra:
            who = " e o ".join(ROLE_WORDS.get(m["name"], m["name"]) for m in extra[:2])
            verb = "descia" if len(extra[:2]) == 1 else "desciam"
            lead += f" Quando recuava perto da área, o {who} {verb} para o meio dos defensores e a linha virava de 5."
        else:
            lead += " Perto da área, a última linha ficava com 5 jogadores."
        lead += " Pouco espaço para entrar."
        return {
            "type": "lowblock", "team": t, "score": 30 + (5 if extra else 0) + max(0, 30 - line) / 2,
            "title": f"{name}: fechou a porta com 5", "lead": lead,
            "roles": last, "line": [{"x": m["x"], "y": m["y"]} for m in members],
            "highlight": [m["name"] for m in extra],
            "takeaway": f"{name} se fechou com 5 perto da área.",
            "before": len(back_line(first)),
        }

    def build_up(self, t: int) -> dict[str, Any] | None:
        info = self.tactics(t).get("buildUp") or {}
        main, share, total = info.get("main") or "", info.get("share") or 0, info.get("total") or 0
        flow = self.flow(t, "ataque")
        if not flow or total < 15 or share < 0.4 or not main.startswith("3"):
            return None
        roles = flow["stages"][0]["roles"]
        members = back_line(roles)
        name = self.names[t]
        pct = round(100 * share)
        if "volante" in main:
            how = "fazia o volante cair entre os zagueiros, formando uma linha de 3"
            after = " Assim, os laterais ficavam livres para subir."
        elif "lateral" in main:
            side = "esquerdo" if "esquerdo" in main else "direito"
            how = f"deixava o lateral {side} atrás com os zagueiros, formando uma linha de 3"
            after = f" Assim, o lateral {'direito' if side == 'esquerdo' else 'esquerdo'} ficava livre para subir."
        else:
            how = "deixava três jogadores atrás"
            after = ""
        return {
            "type": "buildup", "team": t, "score": 18 + pct / 5, "title": f"{name}: saída de bola com 3",
            "lead": f"Para sair jogando, {name} {how}, em {pct}% das saídas que a câmera mostrou inteiras.{after}",
            "roles": roles, "line": [{"x": m["x"], "y": m["y"]} for m in members],
            "highlight": [m["name"] for m in members if m.get("line", 0) > 0],
            "takeaway": f"{name} saiu jogando com 3 atrás.",
        }

    def attack_style(self, t: int) -> dict[str, Any] | None:
        name = self.names[t]
        plays = (self.tactics(t).get("plays") or {}).get("partida") or {}
        counts, by_side = plays.get("counts") or {}, plays.get("bySide") or {}
        crosses, crosses_ok = _official_stat(self.off, "cruzamentos")[t], _official_stat(self.off, "cruzamentos_certos")[t]
        shots, on_target = _official_stat(self.off, "chutes")[t], _official_stat(self.off, "chutes_no_alvo")[t]
        entries = counts.get("entrada", 0)
        inside = by_side.get("corta_dentro") or {}
        side = max(("esquerda", "direita"), key=lambda s: inside.get(s, 0)) if inside else None
        tiles = []
        if crosses is not None:
            tiles.append((str(round(crosses)), "cruzamentos para a área", False))
            if crosses_ok is not None:
                tiles.append((str(round(crosses_ok)), "encontraram um companheiro", True))
        if shots is not None:
            tiles.append((str(round(shots)), "finalizações", False))
            if on_target is not None:
                tiles.append((str(round(on_target)), "no gol", True))
        if not tiles:
            if entries + counts.get("cruzamento", 0) < 4:
                return None
            tiles = [(str(entries), "entradas na área com a bola no pé", False),
                     (str(counts.get("cruzamento", 0)), "cruzamentos para a área", True)]
        if crosses is not None and crosses >= 12:
            ok = round(100 * (crosses_ok or 0) / crosses)
            title = f"{name}: {round(crosses)} cruzamentos, {round(crosses_ok or 0)} certos"
            lead = f"{name} levantou {round(crosses)} bolas na área, mas só {round(crosses_ok or 0)} encontraram um companheiro ({ok}%)."
        elif entries >= max(3, counts.get("cruzamento", 0)):
            title = f"{name}: tocar até entrar"
            lead = f"{name} preferiu trabalhar a jogada a levantar a bola na área."
        else:
            title = f"{name}: como chegou na área"
            lead = f"{name} chegou na área de jeitos diferentes."
        extra = []
        if entries:
            extra.append(f"entrou na área com a bola dominada {entries} {'vez' if entries == 1 else 'vezes'}")
        if side and inside.get(side, 0) >= 2:
            extra.append(f"cortou para dentro pela {side} {inside[side]} vezes")
        if extra:
            lead += " Nos lances que a câmera mostrou, " + " e ".join(extra) + "."
        score = (crosses or 0) / 2 + entries * 2 + (shots or 0) / 3
        return {"type": "counts", "team": t, "score": score, "title": title, "lead": lead, "tiles": tiles[:4],
                "takeaway": lead.split(".")[0] + "."}

    def lines(self) -> dict[str, Any] | None:
        a, b = self.line_height(0), self.line_height(1)
        if a is None or b is None or abs(a - b) < 8:
            return None
        high = 0 if a > b else 1
        low = 1 - high
        h, l = round(max(a, b)), round(min(a, b))
        name, other = self.names[high], self.names[low]
        rec = (self.whole.get("recoveries5s") or [None, None])[high]
        alerts = sum(1 for i in self.insights if i.get("rule") == "linha_alta" and i.get("team") == high)
        lead = f"{name} defendeu, em média, a {h} metros do próprio gol"
        lead += ", perto do meio-campo" if h >= 44 else ""
        lead += f". {other} ficou a {l} metros. Defender alto ajuda a roubar a bola rápido"
        lead += f" ({round(rec)}% das perdas recuperadas em até 5 segundos)" if rec is not None and rec >= 20 else ""
        lead += ", mas deixa muito campo nas costas."
        if alerts >= 2:
            lead += f" O alerta de espaço para a bola longa apareceu {alerts} vezes."
        return {
            "type": "lines", "team": high, "score": abs(a - b), "title": f"{name}: defesa lá em cima",
            "lead": lead, "lines": [(0, round(a)), (1, round(b))],
            "takeaway": f"A melhor chance de {other} era o espaço nas costas da linha alta de {name}.",
        }

    # ---------- cards ----------

    def cover(self) -> dict[str, Any]:
        score = self.score
        poss = self.possession
        names = self.names
        if score is not None:
            a, b = score
            if a == b:
                headline = "Um 0 a 0 nada parado" if a == 0 else (f"Jogo aberto: {a} a {b}" if a >= 2 else f"Empate em {a} a {b}")
            else:
                w = 0 if a > b else 1
                headline = f"{names[w]} venceu"
        else:
            headline = "O jogo por dentro"
        lead = []
        if poss[0] is not None:
            leader = 0 if poss[0] >= poss[1] else 1
            lead.append(f"{names[leader]} teve mais a bola ({round(poss[leader])}%).")
        la, lb = self.line_height(0), self.line_height(1)
        if la is not None and lb is not None and abs(la - lb) >= 6:
            lower = 0 if la < lb else 1
            lead.append(f"{names[lower]} se defendeu mais recuado.")
        lead.append("Nos próximos cards, o que a análise mostrou sobre como cada time jogou.")
        tiles = []
        if poss[0] is not None:
            leader = 0 if poss[0] >= poss[1] else 1
            tiles.append((f"{round(poss[leader])}%", f"de posse de {names[leader]}", leader))
        shots = _official_stat(self.off, "chutes")
        if shots[0] is not None:
            tiles.append((f"{round(shots[0])} x {round(shots[1])}", "finalizações", None))
        for t in (0, 1):
            h = self.line_height(t)
            if h is not None and len(tiles) < 3:
                tiles.append((f"{round(h)} m", f"altura da defesa de {names[t]}", t))
        return {"type": "cover", "headline": headline, "lead": " ".join(lead), "score": score, "tiles": tiles[:3],
                "league": (self.off or {}).get("league"), "date": (self.off or {}).get("date")}

    def goals_card(self) -> dict[str, Any] | None:
        if not self.off:
            return None
        goals = self.off.get("goals") or []
        if not goals:
            return None
        return {"type": "goals", "title": "Os gols", "goals": goals, "lead": _goal_story(goals, self.names, self.score or [0, 0])}

    def control(self) -> dict[str, Any] | None:
        bars = []
        poss = self.possession
        if poss[0] is not None:
            p = _pct_pair(poss[0], poss[1])
            bars.append(("Posse de bola", p[0], p[1], f"{p[0]}%", f"{p[1]}%", ""))
        shots = _official_stat(self.off, "chutes")
        if shots[0] is not None:
            p = _pct_pair(shots[0], shots[1])
            if p:
                bars.append(("Finalizações", p[0], p[1], _n(shots[0]), _n(shots[1]), ""))
        tilt = self.whole.get("tilt")
        if tilt and tilt[0] is not None:
            p = _pct_pair(tilt[0], tilt[1])
            bars.append(("Bola no campo de ataque", p[0], p[1], f"{p[0]}%", f"{p[1]}%", ""))
        rec = self.whole.get("recoveries5s") or [None, None]
        if rec[0] is not None and rec[1] is not None and len(bars) < 4:
            p = _pct_pair(rec[0], rec[1])
            if p:
                bars.append(("Recuperou a bola em até 5 s", p[0], p[1], f"{round(rec[0])}%", f"{round(rec[1])}%", "das perdas"))
        if len(bars) < 2:
            return None
        names = self.names
        text = []
        if poss[0] is not None:
            pl = 0 if poss[0] >= poss[1] else 1
            if shots[0] is not None and shots[0] != shots[1]:
                sl = 0 if shots[0] > shots[1] else 1
                text.append(f"{names[pl]} ficou mais com a bola" + (" e também finalizou mais." if sl == pl else f", mas {names[sl]} finalizou mais."))
            else:
                text.append(f"{names[pl]} ficou mais tempo com a bola.")
        if tilt and tilt[0] is not None and abs(tilt[0] - tilt[1]) >= 8:
            tl = 0 if tilt[0] > tilt[1] else 1
            text.append(f"{names[tl]} passou mais tempo com a bola perto da área adversária.")
        if rec[0] is not None and rec[1] is not None and abs(rec[0] - rec[1]) >= 5:
            rl = 0 if rec[0] > rec[1] else 1
            text.append(f"Quando perdia a bola, {names[rl]} recuperava mais rápido.")
        score = self.score
        if score is not None and poss[0] is not None:
            pl = 0 if poss[0] >= poss[1] else 1
            if score[pl] <= score[1 - pl]:
                text.append("Mas ter o controle não garantiu a vitória.")
        return {"type": "bars", "title": "Quem mandou no jogo?", "bars": bars[:4], "lead": " ".join(text)}

    def build(self) -> list[dict[str, Any]]:
        cards = [self.cover()]
        goals = self.goals_card()
        if goals:
            cards.append(goals)
        control = self.control()
        if control:
            cards.append(control)
        picked: list[dict[str, Any]] = []
        for t in (0, 1):
            options = [c for c in (self.fullbacks(t), self.low_block(t), self.build_up(t)) if c]
            options.sort(key=lambda c: -c["score"])
            types = {p["type"] for p in picked}
            choice = next((c for c in options if c["type"] not in types), options[0] if options else None)
            if choice:
                picked.append(choice)
        cards.extend(picked)
        styles = [c for c in (self.attack_style(0), self.attack_style(1)) if c]
        if styles:
            cards.append(max(styles, key=lambda c: c["score"]))
        lines = self.lines()
        if lines:
            cards.append(lines)
        take = [c["takeaway"] for c in cards if c.get("takeaway")][:3]
        score = self.score
        if score is not None and len(take) < 3:
            take.insert(0, f"Placar final: {self.names[0]} {score[0]} x {score[1]} {self.names[1]}.")
        if take:
            cards.append({
                "type": "takeaways", "title": "Para levar do jogo", "items": take[:3],
                "note": (
                    f"Placar, gols, posse e finalizações oficiais ({(self.off or {}).get('source')}). "
                    if self.off else ""
                ) + f"A parte tática vem da análise por vídeo da transmissão ({self.minutes} minutos analisados) e é aproximada.",
            })
        return cards

    # ---------- relatório ----------

    def comparison(self) -> list[tuple[str, str, str, str, str]]:
        """Linhas (medida, oficial A, oficial B, nossa A, nossa B) para a tabela "oficial × nossa medição"."""
        if not self.off:
            return []
        w = self.whole
        rows = []

        def off(key: str, unit: str = "", digits: int = 0) -> tuple[str, str]:
            v = _official_stat(self.off, key)
            return (_n(v[0], digits) + unit if v[0] is not None else "—", _n(v[1], digits) + unit if v[1] is not None else "—")

        def ours(key: str, unit: str = "", digits: int = 0) -> tuple[str, str]:
            v = w.get(key) or [None, None]
            return (_n(v[0], digits) + unit if v[0] is not None else "—", _n(v[1], digits) + unit if v[1] is not None else "—")

        plays = [((self.tactics(t).get("plays") or {}).get("partida") or {}).get("counts") or {} for t in (0, 1)]
        score = self.score or [0, 0]
        marked = self.stats.get("score") or [0, 0]
        rows.append(("Gols", str(score[0]), str(score[1]), str(marked[0]), str(marked[1])))
        rows.append(("Posse de bola", *off("posse", "%", 1), *ours("possession", "%")))
        rows.append(("Passes", *off("passes"), *ours("passes")))
        rows.append(("Finalizações", *off("chutes"), *(str(p.get("chute_fora", 0) + p.get("chute_dentro", 0)) for p in plays)))
        rows.append(("Cruzamentos", *off("cruzamentos"), *(str(p.get("cruzamento", 0)) for p in plays)))
        rows.append(("Finalizações no gol", *off("chutes_no_alvo"), "—", "—"))
        rows.append(("Escanteios", *off("escanteios"), "—", "—"))
        rows.append(("Faltas", *off("faltas"), "—", "—"))
        rows.append(("Cartões amarelos", *off("amarelos"), "—", "—"))
        return rows

    def summary(self) -> list[str]:
        """Parágrafos do resumo final do relatório (os mesmos textos dos cards)."""
        out = []
        for card in self.build():
            if card["type"] == "takeaways":
                continue
            text = card.get("lead") or ""
            if card["type"] == "cover":
                text = text.replace(" Nos próximos cards, o que a análise mostrou sobre como cada time jogou.", "")
            if text:
                out.append(text)
        return out
