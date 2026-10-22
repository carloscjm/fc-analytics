"""Gera uma partida de exemplo passando posições simuladas pelo motor do FC Analytics.

Salva em out/state.json o mesmo estado que o painel recebe no status inicial
(padrões, estatísticas e insights), para o mock.py servir e o shoot.py fotografar.
Os números são de uma partida simulada; o que se testa aqui é a aparência das telas.

Uso (na raiz do repositório): python tools/preview/gen.py
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from app.patterns import PatternStore
from app.stats import StatsTracker

rng = np.random.default_rng(7)
L, W = 105.0, 68.0
# Formações (time atacando para a direita): posição na saída e o quanto cada uma sobe até a chegada.
A_ATT = [(18, 8, 52), (14, 26, 30), (14, 42, 30), (18, 60, 40), (30, 34, 40), (38, 22, 42), (38, 46, 42), (50, 8, 34), (56, 34, 30), (50, 60, 30)]
A_DEF = [(30, 10, -18), (26, 26, -14), (26, 42, -14), (30, 58, -18), (44, 12, -18), (42, 28, -16), (42, 40, -16), (44, 56, -18), (60, 28, -20), (60, 40, -20)]
B_ATT = [(16, 20, 32), (14, 34, 28), (16, 48, 32), (34, 6, 50), (32, 28, 36), (32, 40, 36), (34, 62, 50), (50, 16, 34), (54, 34, 32), (50, 52, 34)]
B_DEF = [(28, 8, -14), (24, 22, -12), (23, 34, -12), (24, 46, -12), (28, 60, -14), (44, 22, -16), (44, 46, -16), (58, 14, -20), (60, 34, -22), (58, 54, -20)]

def shape(table, s, team, attacking):
    pts = np.array([(x + dx * s, y) for x, y, dx in table], float)
    if not attacking:
        pts[:, 0] = np.array([x + dx * (1 - s) for x, y, dx in table]) + 18  # defende mais alto quando o adversário sai
    pts += rng.normal(0, 1.6, pts.shape)
    if team == 1:  # time 1 defende o gol da direita
        pts = np.column_stack([L - pts[:, 0], W - pts[:, 1]])
    return np.clip(pts, [1, 1], [L - 1, W - 1])

patterns = PatternStore()
stats = StatsTracker(None, now=1000.0)
stats.state, stats.name = "ativa", "Arsenal x Barcelona"
t = 0.0
wall = 1000.0
owner = None
for phase_i in range(90):
    attacker = phase_i % 2 if phase_i % 5 else (phase_i + 1) % 2
    dur = rng.uniform(10, 20)
    steps = int(dur / 0.25)
    owner_j, owner_until = int(rng.integers(0, 5)), 0
    cross_at = steps - 6 if rng.random() < 0.35 else None
    for k in range(steps):
        s = k / steps
        players = []
        tables = {0: (A_ATT if attacker == 0 else A_DEF), 1: (B_ATT if attacker == 1 else B_DEF)}
        pos = {team: shape(tables[team], s, team, team == attacker) for team in (0, 1)}
        if k >= owner_until:
            # passe: a bola vai para outro jogador do time, de preferência mais à frente
            att = pos[attacker]
            ahead = att[:, 0] if attacker == 0 else L - att[:, 0]
            weights = np.exp((ahead - ahead.max()) / 18)
            weights[owner_j] = 0
            owner_j = int(rng.choice(10, p=weights / weights.sum()))
            owner_until = k + int(rng.integers(4, 9))
        bx, by = pos[attacker][owner_j] + [0.6, 0]
        if cross_at is not None and k >= cross_at:
            wing = 6 if (phase_i // 2) % 3 else 62
            if k - cross_at < 3:
                bx, by = (88, wing) if attacker == 0 else (L - 88, W - wing)
            else:
                bx, by = (97, 32) if attacker == 0 else (L - 97, 36)
        for team in (0, 1):
            visible = np.argsort(np.hypot(pos[team][:, 0] - bx, pos[team][:, 1] - by))[:8]
            for j in visible:
                x, y = pos[team][j]
                players.append({"id": team * 100 + int(j), "x": float(x), "y": float(y), "t": team, "l": "jogador", "g": False, "age": 0})
        players.append({"id": 900, "x": 3.0, "y": 34.0, "t": 0, "l": "goleiro", "g": False, "age": 0})
        players.append({"id": 901, "x": 102.0, "y": 34.0, "t": 1, "l": "goleiro", "g": False, "age": 0})
        fm = {"players": players, "ball": {"x": float(bx), "y": float(by), "e": False}}
        patterns.observe(fm, t, view=[[0, 0], [L, 0], [L, W], [0, W]], now=wall)
        stats.observe(fm, True, wall)
        t += 0.25
        wall += 0.25

summary = patterns.summary(now=wall)
st = stats.summary(now=wall)
st.update({"teamNames": ["ARS", "BAR"], "teamNamesSource": "placar", "storageBytes": 48_200_000,
           "teamColors": ["#e05141", "#384f7c"], "score": [1, 1],
           "events": [{"id": 1, "t": 812, "kind": "gol", "team": 0}, {"id": 2, "t": 1290, "kind": "amarelo", "team": 1}, {"id": 3, "t": 1544, "kind": "gol", "team": 1}]})
insights = {
    "items": [
        {"id": 1, "kind": "alerta", "wall": wall * 1000 - 400000, "t": st["elapsedS"] - 400, "team": 1, "rule": "chuveirinho", "level": "atencao",
         "text": "O BAR cruzou 5 bolas na área nos últimos 10 minutos, quase todas pela esquerda."},
        {"id": 2, "kind": "alerta", "wall": wall * 1000 - 200000, "t": st["elapsedS"] - 200, "team": 0, "rule": "linha", "level": "info",
         "text": "O ARS passou a defender com 5 na última linha: o VOL cai entre os zagueiros no bloco baixo."},
        {"id": 3, "kind": "analise", "wall": wall * 1000 - 60000, "t": st["elapsedS"] - 60, "team": None, "rule": None, "level": "info",
         "text": "Análise do LLM", "model": "qwen3:4b-instruct", "seconds": 11,
         "analysis": {"leitura": "O ARS sai com 3 (VOL entre os zagueiros) e acelera pela esquerda com o LE subindo muito; o BAR responde com laterais altos e cruzamentos.",
                      "funcionando": ["Saída com 3 do ARS supera a pressão alta do BAR", "BAR chega bem pelos lados com os alas"],
                      "espacos": ["Costas do LD do BAR quando ele sobe", "Entrelinhas do ARS no bloco médio"],
                      "sugestoes": ["ARS: virar o jogo rápido para o lado direito", "BAR: segurar um volante na saída para não ficar exposto"],
                      "posicoes": ["O LE do ARS apoia por dentro e o PE abre", "O CA do BAR recua para buscar a bola"]}},
    ],
    "llm": {"state": "pronto", "model": "qwen3:4b-instruct", "installed": ["qwen3:4b-instruct"],
            "recommended": [{"name": "qwen3:4b-instruct", "label": "Qwen3 4B (recomendado)"}],
            "intervalS": 120, "intervalOptions": [60, 120, 300, 600], "nextInS": 74, "lastError": None, "pull": None},
}
(HERE / "out").mkdir(exist_ok=True)
json.dump({"patterns": summary, "stats": st, "insights": insights}, open(HERE / "out" / "state.json", "w"), ensure_ascii=False, default=float)
print({k: (v["frames"], v["pattern"] and v["pattern"]["formation"]) for k, v in summary["options"].items()})
print({k: bool(v) for k, v in summary["flows"].items()}, summary["ballArrows"])
print(st["elapsedS"], st["windows"]["partida"]["possession"], st["windows"]["partida"]["passes"])
