"""Testes da leitura tática: saída de bola, jogadas com a bola, posições e mudanças."""

from __future__ import annotations

import numpy as np

from app.tactics import (
    BallPlays,
    build_up_summary,
    change_texts,
    classify_build_up,
    plays_summary,
    plays_texts,
    role_texts,
)


def test_build_up_shapes():
    assert classify_build_up(np.array([[20, 22], [18, 34], [20, 46]], np.float32)) == "3, com o volante entre os zagueiros"
    assert classify_build_up(np.array([[20, 22], [20, 40], [22, 60]], np.float32)) == "3, com o lateral direito ficando"
    assert classify_build_up(np.array([[22, 6], [20, 28], [20, 46]], np.float32)) == "3, com o lateral esquerdo ficando"
    assert classify_build_up(np.array([[20, 26], [20, 42]], np.float32)).startswith("2 zagueiros")
    assert classify_build_up(np.array([[20, 8], [18, 26], [18, 42], [20, 60]], np.float32)) == "4 atrás"
    summary = build_up_summary([(i, "3, com o volante entre os zagueiros") for i in range(20)] + [(30, "4 atrás")] * 5)
    assert summary["main"] == "3, com o volante entre os zagueiros" and summary["total"] == 25


def feed(plays, points, team=0, start=0.0, step=0.15):
    for i, (x, y) in enumerate(points):
        plays.add(start + i * step, team, x, y)


def test_ball_plays():
    plays = BallPlays()
    feed(plays, [(74, 8), (78, 10), (82, 14), (93, 32)])  # cruzamento da esquerda
    feed(plays, [(70, 34), (78, 34), (86, 34), (90, 34)], start=10, step=0.6)  # entrada com a bola dominada
    feed(plays, [(80, 30), (84.5, 31)], start=20)  # chute rápido de fora da área
    feed(plays, [(70, 8), (71, 10), (72, 12), (73, 14), (74, 16), (75, 18), (75, 20), (76, 22)], start=30, step=0.3)  # corta para dentro
    feed(plays, [(66, 62), (68, 62), (70, 62), (72, 63), (75, 63), (78, 63), (80, 63)], start=40, step=0.3)  # vai ao fundo
    plays.add(50, None, None, None)
    counts = plays_summary(list(plays.events), 0)
    assert counts["counts"]["cruzamento"] == 1 and counts["bySide"]["cruzamento"]["esquerda"] == 1
    assert counts["counts"]["entrada"] == 1
    assert counts["counts"]["chute_fora"] == 1
    assert counts["bySide"]["corta_dentro"]["esquerda"] == 1
    assert counts["bySide"]["vai_fundo"]["direita"] == 1
    assert plays_summary(list(plays.events), 1)["counts"]["cruzamento"] == 0


def test_plays_texts_spot_the_chuveirinho():
    whole = {"counts": {"cruzamento": 9, "entrada": 2, "chute_fora": 5, "chute_dentro": 1, "corta_dentro": 0, "vai_fundo": 0},
             "bySide": {"cruzamento": {"esquerda": 6, "direita": 3}, "corta_dentro": {"esquerda": 4, "direita": 0}, "vai_fundo": {"esquerda": 1, "direita": 3}}}
    texts = " ".join(plays_texts(whole, whole))
    assert "chuveirinho" in texts and "Arrisca muito de fora" in texts
    assert "Pela esquerda, a jogada costuma cortar para dentro" in texts
    assert "Pela direita, a jogada costuma ir ao fundo" in texts


def role(name, x, y, line):
    return {"name": name, "x": x, "y": y, "line": line}


ATTACK = {"roles": [
    role("ZAG", 30, 24, 0), role("ZAG", 30, 44, 0), role("LD", 46, 60, 0),
    role("VOL", 33, 34, 1), role("LE", 66, 5, 1), role("MC", 52, 40, 1),
    role("PE", 72, 16, 2), role("MEI", 70, 34, 2), role("PD", 74, 64, 2), role("CA", 84, 34, 3),
], "formation": "3-3-3-1", "lineHeight": 33.0}
DEFENSE = {"roles": [role("LE", 20, 8, 0), role("ZAG", 18, 26, 0), role("ZAG", 18, 42, 0), role("LD", 20, 60, 0)],
           "formation": "4-4-2", "lineHeight": 19.0}


def test_role_texts_describe_each_position():
    texts = " | ".join(role_texts(ATTACK, DEFENSE, None))
    assert "Defende com 4 atrás" in texts
    assert "LE (lateral esquerdo): sobe e apoia" in texts and "por fora, colado na linha lateral" in texts
    assert "passa por fora do PE, que fecha para o meio" in texts
    assert "LD (lateral direito): fica mais atrás" not in texts  # 40 m: avança até o meio-campo
    assert "VOL (volante): recua para a altura dos zagueiros" in texts
    assert "MEI (meia): joga entre as linhas" in texts
    assert "CA (centroavante): fica na referência" in texts


def test_change_texts_compare_windows():
    earlier = {"roles": [dict(r) for r in ATTACK["roles"]]}
    recent = {"roles": [dict(r) for r in ATTACK["roles"]]}
    recent["roles"][4]["y"] = 22  # o LE passou a jogar por dentro
    texts = " | ".join(change_texts(ATTACK, earlier, recent, 4, 5, "4 atrás", "3, com o volante entre os zagueiros"))
    assert "Passou a defender com 5 atrás (antes eram 4)" in texts
    assert "Na saída de bola, passou de 4 atrás para 3, com o volante entre os zagueiros" in texts
    assert "LE: antes jogava por fora" in texts and "agora por dentro" in texts
