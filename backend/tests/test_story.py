"""História da partida (story.py), cards do Instagram (cards.py) e relatório com os dados oficiais."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from app.cards import build_cards, text_width, wrap
from app.official import assign, ordered, parse_summary
from app.report import build_report
from app.story import Story, _goal_story, team_names

FIX = Path(__file__).parent / "fixtures"
STATE = json.loads((FIX / "match_state.json").read_text(encoding="utf-8"))
SUMMARY = json.loads((FIX / "espn_summary.json").read_text(encoding="utf-8"))


def with_official() -> dict:
    stats = copy.deepcopy(STATE["stats"])
    off = parse_summary(SUMMARY, "401915312")
    off["order"] = assign(off, stats.get("teamNames") or [None, None])
    stats["official"] = ordered(off)
    return stats


def test_official_numbers_win():
    stats = with_official()
    story = Story(stats, STATE["patterns"], STATE["insights"])
    assert team_names(stats) == ["Arsenal", "Bayern"]
    assert story.score == [2, 2]  # o placar marcado no app era 1 x 1
    assert round(story.possession[0]) == 54
    gols = next(r for r in story.comparison() if r[0] == "Gols")
    assert gols == ("Gols", "2", "2", "1", "1")


def test_goal_story_reads_like_people_talk():
    names = ["Arsenal", "Bayern"]
    goals = [{"team": 0, "minute": "25'"}, {"team": 1, "minute": "35'"}, {"team": 1, "minute": "61'"}, {"team": 0, "minute": "82'"}]
    assert _goal_story(goals, names, [2, 2]) == (
        "Arsenal saiu na frente aos 25', Bayern empatou aos 35', Bayern virou aos 61' e Arsenal empatou aos 82'."
    )
    two = [{"team": 0, "minute": "10'"}, {"team": 0, "minute": "50'"}, {"team": 1, "minute": "80'"}]
    assert _goal_story(two, names, [2, 1]) == "Arsenal saiu na frente aos 10', Arsenal ampliou aos 50' e Bayern descontou aos 80'."


def test_cards_with_and_without_official():
    story = Story(with_official(), STATE["patterns"], STATE["insights"])
    types = [c["type"] for c in story.build()]
    assert types[0] == "cover" and types[1] == "goals" and types[-1] == "takeaways"
    assert len(types) == len(set(types)) or types.count("lowblock") <= 1
    plain = Story(copy.deepcopy(STATE["stats"]), STATE["patterns"], STATE["insights"]).build()
    assert "goals" not in [c["type"] for c in plain]  # sem dados oficiais não há lista de gols
    assert "ESPN" not in plain[-1]["note"]


def test_every_text_names_the_team():
    """Os parágrafos do resumo saem soltos no relatório, então cada um precisa dizer de qual time fala."""
    story = Story(with_official(), STATE["patterns"], STATE["insights"])
    for text in story.summary():
        assert "Arsenal" in text or "Bayern" in text, text


def test_wrap_respects_width():
    text = "Arsenal levantou 17 bolas na área, mas só 4 encontraram um companheiro."
    lines = wrap(text, "inter-500", 40, 500, names=["Arsenal"], colors=["#f00"])
    assert len(lines) > 1
    for line in lines:
        assert text_width(" ".join(w for w, _ in line), "inter-500", 40) <= 500
    assert lines[0][0] == ("Arsenal", "#f00")


def test_cards_svg_are_valid_and_carry_fonts():
    import xml.etree.ElementTree as ET

    cards = build_cards(with_official(), STATE["patterns"], STATE["insights"])
    assert len(cards) >= 5
    for i, svg in enumerate(cards, 1):
        root = ET.fromstring(svg)
        assert root.get("width") == "1080" and root.get("height") == "1350"
        assert "font/woff2;base64" in svg
        assert f"{i}/{len(cards)}" in svg
    light = build_cards(with_official(), STATE["patterns"], STATE["insights"], embed_fonts=False)
    assert all("base64" not in s for s in light)


def test_report_has_official_section_summary_and_cards():
    html = build_report(with_official(), STATE["patterns"], STATE["insights"], None, "0.0.0")
    assert "Placar oficial" in html and "Dados oficiais" in html and "Resumo final" in html
    assert "Eberechi Eze" in html
    assert len(re.findall(r'<figure id="card-\d+">', html)) >= 5
    assert html.count("font/woff2;base64") == 5  # as fontes vão uma vez só na página
    plain = build_report(copy.deepcopy(STATE["stats"]), STATE["patterns"], STATE["insights"], None, "0.0.0")
    assert "Não conferido" in plain
