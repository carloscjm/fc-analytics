"""Dados oficiais da partida, para conferir e completar o que a câmera mediu.

A análise por vídeo acerta bem a posse e a parte tática, mas não sabe o placar
(só pelos gols marcados à mão) e conta menos passes, chutes e cruzamentos do que
houve, porque a câmera não mostra tudo. Ao finalizar a partida, o app procura o
jogo numa fonte pública e gratuita e, depois de a pessoa confirmar, usa o placar,
os gols, os cartões e as estatísticas oficiais no relatório e nos cards.

Fonte: a API pública do site da ESPN (sem chave). Ela não é documentada nem
garantida: pode mudar sem aviso, então tudo aqui é tolerante a campos faltando e,
se falhar, o relatório sai como antes, avisando que não foi conferido.
Uma consulta por partida (mais a busca do dia), sem consultas repetidas.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

log = logging.getLogger("fc-analytics")

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/all"
TIMEOUT_S = 12.0
SOURCE = "ESPN"

# Estatísticas oficiais usadas (nome na ESPN → nome no app).
STATS = {
    "possessionPct": "posse",
    "totalShots": "chutes",
    "shotsOnTarget": "chutes_no_alvo",
    "wonCorners": "escanteios",
    "foulsCommitted": "faltas",
    "yellowCards": "amarelos",
    "redCards": "vermelhos",
    "offsides": "impedimentos",
    "saves": "defesas",
    "totalPasses": "passes",
    "accuratePasses": "passes_certos",
    "totalCrosses": "cruzamentos",
    "accurateCrosses": "cruzamentos_certos",
}

# Palavras que aparecem no nome da partida mas não identificam time.
STOPWORDS = {
    "x", "vs", "versus", "contra", "fc", "cf", "sc", "ac", "afc", "cl", "ucl", "uel", "jogo", "partida",
    "de", "do", "da", "e", "the", "club", "clube", "futebol", "football", "champions", "league", "liga",
    "copa", "rodada", "final", "semifinal", "ida", "volta",
}

Fetch = Callable[[str], Any]


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "FC-Analytics/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 (endereço fixo da ESPN)
        return json.load(res)


def _plain(text: str) -> str:
    """Minúsculas, sem acento e só letras/números (para comparar nomes)."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def name_tokens(*texts: str | None) -> list[str]:
    """Pedaços que podem identificar um time: siglas e palavras do nome da partida (sem datas e números)."""
    out: list[str] = []
    for text in texts:
        for word in _plain(text or "").split():
            if len(word) < 3 or word.isdigit() or word in STOPWORDS:
                continue
            if word not in out:
                out.append(word)
    return out


def team_score(tokens: list[str], team: dict[str, Any]) -> float:
    """Quanto os pedaços combinam com um time da ESPN (0 = nada; 1 = combina bem)."""
    abbr = _plain(team.get("abbreviation", ""))
    words = set()
    for key in ("displayName", "shortDisplayName", "name", "location"):
        words.update(_plain(team.get(key, "")).split())
    best = 0.0
    for tok in tokens:
        if tok == abbr:
            best = max(best, 1.0)
        elif tok in words:
            best = max(best, 1.0)
        elif any(w.startswith(tok) for w in words if len(tok) >= 3):
            best = max(best, 0.8)  # "bay" → "bayern"
        elif len(tok) >= 4 and any(tok.startswith(w) for w in words if len(w) >= 4):
            best = max(best, 0.6)
    return best


def _competitors(event: dict[str, Any]) -> list[dict[str, Any]]:
    comps = (event.get("competitions") or [{}])[0].get("competitors") or []
    return sorted(comps, key=lambda c: 0 if c.get("homeAway") == "home" else 1)


def _candidate(event: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    comps = _competitors(event)
    teams = [c.get("team") or {} for c in comps]
    scores = sorted((team_score(tokens, t) for t in teams), reverse=True)
    match = scores[0] + (scores[1] if len(scores) > 1 else 0.0)
    status = ((event.get("status") or {}).get("type") or {})
    return {
        "eventId": str(event.get("id")),
        "name": event.get("name"),
        "date": event.get("date"),
        "league": (event.get("season") or {}).get("slug"),
        "status": status.get("description") or status.get("name"),
        "completed": bool(status.get("completed")),
        "home": {"name": teams[0].get("displayName") if teams else None, "abbr": teams[0].get("abbreviation") if teams else None,
                 "score": comps[0].get("score") if comps else None},
        "away": {"name": teams[1].get("displayName") if len(teams) > 1 else None,
                 "abbr": teams[1].get("abbreviation") if len(teams) > 1 else None,
                 "score": comps[1].get("score") if len(comps) > 1 else None},
        "match": round(match, 2),
    }


def search_dates(started: float) -> list[str]:
    """Dias para procurar (AAAAMMDD, UTC): o dia do jogo e os vizinhos (fuso horário e jogos de madrugada)."""
    day = datetime.fromtimestamp(started, tz=timezone.utc)
    return [(day + timedelta(days=d)).strftime("%Y%m%d") for d in (0, -1, 1)]


def search(
    names: list[str | None],
    match_name: str | None,
    started: float,
    query: str | None = None,
    date: str | None = None,
    fetch: Fetch = _fetch_json,
) -> list[dict[str, Any]]:
    """Jogos do dia que combinam com os nomes, do mais provável para o menos (no máximo 6)."""
    tokens = name_tokens(query) if query else name_tokens(*(names or []), match_name)
    dates = [re.sub(r"\D", "", date)] if date else search_dates(started)
    seen: dict[str, dict[str, Any]] = {}
    for day in dates:
        try:
            data = fetch(f"{BASE}/scoreboard?dates={day}&limit=500")
        except Exception:  # noqa: BLE001 - sem internet ou fonte fora do ar
            log.warning("busca dos dados oficiais falhou (%s)", day, exc_info=True)
            continue
        for event in data.get("events") or []:
            cand = _candidate(event, tokens)
            if cand["match"] >= 0.8 and cand["eventId"] not in seen:
                seen[cand["eventId"]] = cand
        if any(c["match"] >= 1.6 for c in seen.values()):
            break  # achou um jogo que combina com os dois times: não precisa olhar os outros dias
    return sorted(seen.values(), key=lambda c: (-c["match"], not c["completed"]))[:6]


def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace("%", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_summary(data: dict[str, Any], event_id: str) -> dict[str, Any]:
    """Resumo oficial: times (casa, fora), placar, gols, cartões e estatísticas."""
    header = data.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    comps = sorted(comp.get("competitors") or [], key=lambda c: 0 if c.get("homeAway") == "home" else 1)
    teams = []
    for c in comps:
        t = c.get("team") or {}
        teams.append({
            "id": str(t.get("id")),
            "name": t.get("displayName"),
            "short": t.get("shortDisplayName") or t.get("displayName"),
            "abbr": t.get("abbreviation"),
            "homeAway": c.get("homeAway"),
            "score": int(_num(c.get("score")) or 0),
            "color": f"#{t['color']}" if t.get("color") else None,
            "stats": {},
        })
    by_id = {t["id"]: t for t in teams}
    for bt in (data.get("boxscore") or {}).get("teams") or []:
        team = by_id.get(str((bt.get("team") or {}).get("id")))
        if team is None:
            continue
        for s in bt.get("statistics") or []:
            key = STATS.get(s.get("name"))
            value = _num(s.get("displayValue"))
            if key and value is not None:
                team["stats"][key] = value
    goals, cards = [], []
    for e in data.get("keyEvents") or []:
        kind = ((e.get("type") or {}).get("type") or "").lower()
        team_id = str((e.get("team") or {}).get("id"))
        side = next((i for i, t in enumerate(teams) if t["id"] == team_id), None)
        people = [((p.get("athlete") or {}).get("displayName")) for p in e.get("participants") or []]
        minute = (e.get("clock") or {}).get("displayValue")
        text = (e.get("text") or "").lower()
        if e.get("scoringPlay"):
            goals.append({
                "minute": minute,
                "team": side,
                "player": people[0] if people else None,
                "assist": people[1] if len(people) > 1 and "penalty" not in kind else None,
                "penalty": "penalty" in kind,
                "ownGoal": "own" in kind or "own goal" in text,
            })
        elif "card" in kind:
            cards.append({"minute": minute, "team": side, "player": people[0] if people else None,
                          "kind": "vermelho" if "red" in kind else "amarelo"})
    status = (comp.get("status") or {}).get("type") or {}
    return {
        "source": SOURCE,
        "eventId": str(event_id),
        "league": (header.get("league") or {}).get("name"),
        "date": comp.get("date"),
        "venue": ((data.get("gameInfo") or {}).get("venue") or {}).get("fullName"),
        "completed": bool(status.get("completed")),
        "status": status.get("name"),
        "teams": teams,
        "goals": goals,
        "cards": cards,
        "fetchedAt": round(time.time()),
    }


def fetch_summary(event_id: str, fetch: Fetch = _fetch_json) -> dict[str, Any]:
    event_id = re.sub(r"\D", "", str(event_id))
    data = fetch(f"{BASE}/summary?event={urllib.parse.quote(event_id)}")
    return parse_summary(data, event_id)


def assign(official: dict[str, Any], names: list[str | None]) -> list[int]:
    """Qual time oficial é o nosso Time A e qual é o Time B: `order[i]` = índice em official["teams"] do time i."""
    teams = official.get("teams") or []
    if len(teams) != 2:
        return [0, 1]
    ours = [name_tokens(n) for n in (names or [None, None])[:2]]
    straight = team_score(ours[0], teams[0]) + team_score(ours[1], teams[1])
    crossed = team_score(ours[0], teams[1]) + team_score(ours[1], teams[0])
    # Empate (nenhuma sigla ajuda): fica a ordem casa/fora, e a pessoa troca na tela de conferência se precisar.
    return [0, 1] if straight >= crossed else [1, 0]


def ordered(official: dict[str, Any] | None) -> dict[str, Any] | None:
    """Os dados oficiais na ordem dos nossos times (0 = Time A, 1 = Time B), com os gols e cartões remapeados."""
    if not official or len(official.get("teams") or []) != 2:
        return None
    order = official.get("order") or [0, 1]
    back = {src: ours for ours, src in enumerate(order)}
    teams = [official["teams"][i] for i in order]
    goals = [{**g, "team": back.get(g["team"])} for g in official.get("goals") or []]
    cards = [{**c, "team": back.get(c["team"])} for c in official.get("cards") or []]
    return {**official, "teams": teams, "goals": goals, "cards": cards}
