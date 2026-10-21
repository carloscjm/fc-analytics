"""Testes da leitura dos nomes dos times no placar."""

from __future__ import annotations

import numpy as np
import pytest

from app.insights import build_summary, evaluate_rules
from app.teamnames import TeamNameReader, TeamNames, Token, clean_names, find_pair


def tok(text, x0, y0, x1, y1, score=0.99):
    return Token(text, x0, y0, x1, y1, score)


def test_pair_in_one_token_or_split_on_the_line():
    assert find_pair([tok("36:25", 0, 0, 40, 20), tok("MCI 0 3 PSG", 50, 0, 160, 20)])[0] == ("MCI", "PSG")
    assert find_pair([tok("VAS", 50, 0, 80, 20), tok("0-2", 90, 0, 110, 20), tok("BOC", 120, 0, 150, 20)])[0] == ("VAS", "BOC")
    assert find_pair([tok("MCI", 10, 0, 40, 20), tok("PSG", 140, 0, 170, 20), tok("SPORTS", 600, 0, 700, 20)])[0] == ("MCI", "PSG")
    # O leitor quebrou o placar em dois pedaços.
    assert find_pair([tok("36:25", 0, 0, 40, 20), tok("MCI", 50, 0, 80, 20), tok("0 3 PSG", 88, 0, 150, 20)])[0] == ("MCI", "PSG")


def test_stacked_scoreboard_and_noise():
    stacked = [tok("ARS", 10, 10, 40, 30), tok("1", 50, 10, 60, 30), tok("CHE", 10, 35, 40, 55), tok("0", 50, 35, 60, 55)]
    assert find_pair(stacked)[0] == ("ARS", "CHE")
    noise = [tok("UEFA", 10, 0, 50, 20), tok("LIVE", 60, 0, 90, 20), tok("crypto.com", 100, 0, 200, 20)]
    assert find_pair(noise) is None
    far = [tok("MCI", 0, 0, 30, 20), tok("PSG", 700, 0, 730, 20)]
    assert find_pair(far) is None


class FakeResult:
    def __init__(self, items):
        self.boxes = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] for _, x0, y0, x1, y1 in items]
        self.txts = [t for t, *_ in items]
        self.scores = [0.99] * len(items)


class FakeEngine:
    def __init__(self, reads):
        self.reads = list(reads)

    def __call__(self, image):
        return FakeResult(self.reads.pop(0) if self.reads else [])


def test_reader_confirms_after_repeated_reads():
    line = [("MCI 0 3 PSG", 50, 5, 160, 25)]
    reader = TeamNameReader(engine_factory=lambda: FakeEngine([line, [], line, line]))
    band = np.zeros((60, 400, 3), dtype=np.uint8)
    for _ in range(3):
        reader.read(band)
    assert reader.decide(None) is None  # 2 de 3 leituras: ainda não
    reader.read(band)
    names = reader.decide(["#ffffff", "#203060"])
    assert names.names == ["MCI", "PSG"] and names.source == "placar"


def test_names_follow_the_shirt_colors():
    names = TeamNames(names=["MCI", "PSG"], anchors=["#a0d0f0", "#1a2a5a"], source="placar")
    assert names.ordered(["#a2d2ee", "#1c2c58"]) == ["MCI", "PSG"]
    # A calibração recomeçou e os times trocaram de índice: os nomes acompanham a cor.
    assert names.ordered(["#1c2c58", "#a2d2ee"]) == ["PSG", "MCI"]
    assert TeamNames().ordered(None) == [None, None]


def test_clean_names():
    assert clean_names([" Flamengo  ", "PAL"]) == ["Flamengo", "PAL"]
    with pytest.raises(ValueError):
        clean_names(["", "PAL"])
    with pytest.raises(ValueError):
        clean_names(["só um"])


def test_insights_use_team_names():
    from tests.test_insights import stats, window

    s = stats(window(possession=[70.0, 30.0]))
    s["teamNames"] = ["MCI", "PSG"]
    assert evaluate_rules(s)[0].text.startswith("MCI domina a posse")
    summary = build_summary(s, None, [])
    assert summary["placar"] == "MCI 1 x 0 PSG"
    assert summary["partida_inteira"]["posse_pct"] == {"MCI": 70, "PSG": 30}
