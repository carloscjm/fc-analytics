"""Dados oficiais (ESPN): busca pelo nome dos times, resumo e ligação com o Time A e o Time B."""

from __future__ import annotations

import json
from pathlib import Path

from app.official import assign, fetch_summary, name_tokens, ordered, search

FIX = Path(__file__).parent / "fixtures"
SCOREBOARD = json.loads((FIX / "espn_scoreboard.json").read_text(encoding="utf-8"))
SUMMARY = json.loads((FIX / "espn_summary.json").read_text(encoding="utf-8"))
STARTED = 1792609740.0  # 21/10/2026 17:09 em São Paulo


def fake_fetch(urls):
    def fetch(url):
        urls.append(url)
        return SUMMARY if "summary" in url else SCOREBOARD
    return fetch


def test_tokens_ignore_dates_and_filler():
    assert name_tokens("BAY", "ARS", "arsenal x bayern 21-10 cl") == ["bay", "ars", "arsenal", "bayern"]


def test_search_finds_the_match_from_siglas_and_match_name():
    urls = []
    found = search(["BAY", "ARS"], "arsenal x bayern 21-10 cl", STARTED, fetch=fake_fetch(urls))
    assert found[0]["eventId"] == "401915312"
    assert found[0]["match"] >= 1.6
    assert all(c["eventId"] != "401915313" for c in found)
    assert len(urls) == 1 and "dates=20261021" in urls[0]  # achou no primeiro dia: não procura nos vizinhos


def test_manual_query_and_date():
    found = search([None, None], None, STARTED, query="Real Madrid Leipzig", date="2026-10-21", fetch=fake_fetch([]))
    assert found[0]["eventId"] == "401915313"


def test_search_without_internet_returns_nothing():
    def broken(url):
        raise OSError("sem rede")
    assert search(["BAY", "ARS"], None, STARTED, fetch=broken) == []


def test_summary_and_team_order():
    official = fetch_summary("401915312", fetch=fake_fetch([]))
    home, away = official["teams"]
    assert (home["short"], home["score"], away["short"], away["score"]) == ("Bayern", 2, "Arsenal", 2)
    assert away["stats"]["posse"] == 53.9 and away["stats"]["cruzamentos"] == 17
    assert [g["minute"] for g in official["goals"]] == ["25'", "35'", "61'", "82'"]
    assert official["goals"][2]["penalty"] and official["goals"][2]["assist"] is None
    assert official["goals"][0]["assist"] == "Martin Ødegaard"
    assert [c["kind"] for c in official["cards"]] == ["amarelo", "amarelo"]
    # Nosso Time A é "BAY" (Bayern) e o Time B "ARS": casa = A, fora = B.
    assert assign(official, ["BAY", "ARS"]) == [0, 1]
    assert assign(official, ["ARS", "BAY"]) == [1, 0]
    swapped = ordered({**official, "order": [1, 0]})
    assert swapped["teams"][0]["short"] == "Arsenal"
    assert swapped["goals"][0]["team"] == 0  # gol do Arsenal, agora Time A
