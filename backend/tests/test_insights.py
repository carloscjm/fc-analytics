"""Testes dos insights (Fase 5): regras com estatísticas sintéticas e o LLM com um Ollama falso."""

from __future__ import annotations

import copy
import json
import time

import pytest

from app.insights import (
    ALERT_COOLDOWN_S,
    InsightEngine,
    build_summary,
    evaluate_rules,
    parse_analysis,
)
from app.stats import MatchStore


def window(**over):
    base = {
        "seconds": 240.0, "possession": [50.0, 50.0], "possessionCoverage": 80.0, "tilt": [50.0, 50.0],
        "line": [35.0, 35.0], "depth": [38.0, 38.0], "width": [45.0, 45.0],
        "corridors": [[33.0, 34.0, 33.0], [33.0, 34.0, 33.0]], "passes": [10, 10], "losses": [3, 3],
        "passAccuracy": [77.0, 77.0], "pressure": [1.0, 1.0], "recoveries5s": [20.0, 20.0], "distanceKm": [1.0, 1.0],
    }
    base.update(over)
    return base


def stats(recent=None, line=None, match_id=1, elapsed=600.0, events=None, paused=False):
    recent = recent or window()
    return {
        "matchId": match_id, "startedAt": 0, "elapsedS": elapsed, "paused": paused, "period": 1,
        "score": [1, 0], "events": events or [],
        "windows": {"recentes": recent, "partida": copy.deepcopy(recent)},
        "timeline": {"minutes": [1, 2, 3, 4], "possession": [None] * 4, "line": line or [[35, 35, 35, 35], [35, 35, 35, 35]]},
    }


def rules_of(alerts):
    return {(a.rule, a.team) for a in alerts}


def test_quiet_game_has_no_alerts():
    assert evaluate_rules(stats()) == []


def test_rules_fire_on_thresholds():
    recent = window(
        possession=[70.0, 30.0], tilt=[75.0, 25.0], corridors=[[65.0, 20.0, 15.0], None],
        losses=[2, 7], passAccuracy=[90.0, 55.0], recoveries5s=[60.0, 0.0], depth=[40.0, 50.0],
    )
    recent["losses"][0] = 5
    found = rules_of(evaluate_rules(stats(recent, line=[[30, 46, 47, 48], [24, 22, 20, 21]])))
    assert ("linha_alta", 0) in found
    assert ("bloco_baixo", 1) in found
    assert ("posse", 0) in found
    assert ("territorio", 0) in found
    assert ("corredor", 0) in found
    assert ("perdas", 1) in found
    assert ("pressao", 0) in found
    assert ("espacado", 1) in found
    texts = " ".join(a.text for a in evaluate_rules(stats(recent, line=[[30, 46, 47, 48], [24, 22, 20, 21]])))
    assert "lado esquerdo" in texts and "Time B" in texts


def test_rules_need_enough_play():
    recent = window(seconds=40.0, possession=[80.0, 20.0], tilt=[90.0, 10.0])
    assert evaluate_rules(stats(recent)) == []


def test_parse_analysis_accepts_wrapped_json_and_trims():
    content = 'Claro! {"leitura": "Jogo equilibrado.", "funcionando": ["a", "b", "c", "d"], "espacos": "lado direito", "sugestoes": []}'
    parsed = parse_analysis(content)
    assert parsed["leitura"] == "Jogo equilibrado."
    assert parsed["funcionando"] == ["a", "b", "c"]
    assert parsed["espacos"] == ["lado direito"]
    with pytest.raises(ValueError):
        parse_analysis("sem json aqui")
    with pytest.raises(ValueError):
        parse_analysis('{"leitura": ""}')


def test_summary_for_the_llm_is_readable():
    patterns = {"options": {"0-ataque": {"pattern": {"formation": "4-3-3", "lineHeight": 38.0, "width": 50.0}}, "1-defesa": {"pattern": None}}}
    events = [{"id": 1, "t": 125.0, "kind": "gol", "team": 0}, {"id": 2, "t": 300.0, "kind": "intervalo", "team": None}]
    summary = build_summary(stats(events=events), patterns, ["alerta 1"])
    assert summary["placar"] == "Time A 1 x 0 Time B"
    assert summary["eventos"] == [{"minuto": 3, "evento": "gol", "time": "Time A"}]
    assert summary["padroes"]["Time A atacando"]["formacao"] == "4-3-3"
    assert summary["ultimos_5_minutos"]["posse_pct"] == {"Time A": 50, "Time B": 50}
    json.dumps(summary, ensure_ascii=False)
    # Pouco jogo nos últimos 5 min: só um aviso, para o modelo não tirar conclusões de 10 segundos.
    short = build_summary(stats(window(seconds=10.0)), None, [])
    assert "aviso" in short["ultimos_5_minutos"] and "posse_pct" not in short["ultimos_5_minutos"]
    assert "posse_pct" in short["partida_inteira"]


class FakeOllama:
    def __init__(self, installed=("qwen3:4b-instruct",), reply=None, fail=False):
        self.installed = list(installed)
        self.reply = reply or json.dumps({
            "leitura": "O Time A controla o jogo pela esquerda.",
            "funcionando": ["Time A: troca de passes curta"],
            "espacos": ["Time B deixa espaço nas costas dos laterais"],
            "sugestoes": ["Time B: baixar o bloco 5 m"],
        })
        self.fail = fail
        self.calls = []

    def models(self):
        return list(self.installed)

    def chat(self, model, system, user, schema):
        self.calls.append((model, user))
        if self.fail:
            raise OSError("conexão recusada")
        return self.reply

    def pull(self, model, progress):
        for done in (0, 50, 100):
            progress({"status": "baixando", "total": 100, "completed": done})
        self.installed.append(model)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_alert_cooldown_and_feed():
    clock = Clock()
    engine = InsightEngine(ollama=FakeOllama(installed=()), clock=clock)
    hot = stats(window(possession=[70.0, 30.0]))
    engine.on_stats(hot, None)
    engine.on_stats(hot, None)
    alerts = [i for i in engine.snapshot()["items"] if i["kind"] == "alerta"]
    assert len(alerts) == 1 and alerts[0]["team"] == 0
    clock.now += ALERT_COOLDOWN_S + 1
    engine.on_stats(hot, None)
    assert len([i for i in engine.snapshot()["items"] if i["kind"] == "alerta"]) == 2
    # Partida nova: feed vazio.
    engine.on_stats(stats(window(), match_id=2), None)
    assert engine.snapshot()["items"] == []


def test_llm_analysis_runs_in_background_and_lands_in_the_feed():
    clock = Clock()
    fake = FakeOllama()
    engine = InsightEngine(ollama=fake, clock=clock)
    engine.check()
    assert engine.snapshot()["llm"]["state"] == "pronto"
    engine.on_stats(stats(), None)
    assert engine.analyze_now() is True
    assert wait_for(lambda: any(i["kind"] == "analise" for i in engine.snapshot()["items"]))
    item = [i for i in engine.snapshot()["items"] if i["kind"] == "analise"][0]
    assert item["analysis"]["sugestoes"] == ["Time B: baixar o bloco 5 m"]
    assert item["model"] == "qwen3:4b-instruct"
    snap = engine.snapshot()["llm"]
    assert snap["state"] == "pronto" and snap["nextInS"] == 240
    assert '"placar": "Time A 1 x 0 Time B"' in fake.calls[0][1]


def test_llm_schedule_waits_for_new_play():
    clock = Clock()
    fake = FakeOllama()
    engine = InsightEngine(ollama=fake, clock=clock)
    engine.check()
    engine.on_stats(stats(), None)  # agenda a primeira análise para daqui a 1 min
    assert fake.calls == []
    clock.now += 61
    engine.tick()
    assert wait_for(lambda: len(fake.calls) == 1 and not engine.llm.busy)
    clock.now += 241
    engine.tick()  # sem jogo novo analisado: não chama de novo
    time.sleep(0.1)
    assert len(fake.calls) == 1
    more = stats(window(seconds=400.0))
    engine.on_stats(more, None)
    clock.now += 31
    engine.tick()
    assert wait_for(lambda: len(fake.calls) == 2)


def test_llm_errors_and_missing_model():
    engine = InsightEngine(ollama=FakeOllama(installed=()), clock=Clock())
    engine.check()
    assert engine.snapshot()["llm"]["state"] == "sem modelo"
    engine.on_stats(stats(), None)
    assert engine.analyze_now() is False
    assert "não foi baixado" in engine.snapshot()["llm"]["lastError"]

    failing = InsightEngine(ollama=FakeOllama(fail=True), clock=Clock())
    failing.check()
    failing.on_stats(stats(), None)
    failing.analyze_now()
    assert wait_for(lambda: failing.snapshot()["llm"]["lastError"] is not None)
    assert failing.snapshot()["llm"]["state"] == "pronto"
    assert not [i for i in failing.snapshot()["items"] if i["kind"] == "analise"]


def test_pull_model_and_settings(tmp_path):
    fake = FakeOllama(installed=())
    settings = tmp_path / "llm.json"
    engine = InsightEngine(ollama=fake, clock=Clock(), settings_path=settings)
    engine.check()
    engine.set_model("qwen3:8b")
    engine.set_interval(300)
    assert json.loads(settings.read_text())["model"] == "qwen3:8b"
    assert engine.pull() is True
    assert wait_for(lambda: engine.snapshot()["llm"]["state"] == "pronto")
    assert "qwen3:8b" in fake.installed
    again = InsightEngine(ollama=fake, clock=Clock(), settings_path=settings)
    assert again.llm.model == "qwen3:8b" and again.llm.interval_s == 300
    with pytest.raises(ValueError):
        engine.set_interval(10)


def test_insights_are_saved_with_the_match(tmp_path):
    store = MatchStore(tmp_path / "partidas.sqlite")
    match_id = store.new_match(0.0)
    engine = InsightEngine(store=store, ollama=FakeOllama(installed=()), clock=Clock())
    engine.on_stats(stats(window(possession=[70.0, 30.0]), match_id=match_id), None)
    again = InsightEngine(store=store, ollama=FakeOllama(installed=()), clock=Clock())
    again.bind_match(match_id)
    items = again.snapshot()["items"]
    assert len(items) == 1 and items[0]["rule"] == "posse"


def test_remove_and_clear_feed(tmp_path):
    store = MatchStore(tmp_path / "partidas.sqlite")
    match_id = store.new_match(0.0)
    clock = Clock()
    engine = InsightEngine(store=store, ollama=FakeOllama(installed=()), clock=clock)
    hot = stats(window(possession=[70.0, 30.0], tilt=[75.0, 25.0]), match_id=match_id)
    engine.on_stats(hot, None)
    items = engine.snapshot()["items"]
    assert len(items) == 2
    assert engine.remove(items[0]["id"]) is True
    assert engine.remove(9999) is False
    assert [i["id"] for i in engine.snapshot()["items"]] == [items[1]["id"]]
    # Apagado também no banco.
    again = InsightEngine(store=store, ollama=FakeOllama(installed=()), clock=clock)
    again.bind_match(match_id)
    assert len(again.snapshot()["items"]) == 1
    # Limpar tudo não faz os mesmos alertas voltarem na hora (o tempo de espera continua).
    assert engine.clear() == 1
    engine.on_stats(hot, None)
    assert engine.snapshot()["items"] == []
    fresh = InsightEngine(store=store, ollama=FakeOllama(installed=()), clock=clock)
    fresh.bind_match(match_id)
    assert fresh.snapshot()["items"] == []


def test_tactic_alerts_and_llm_summary():
    from app.insights import tactic_alerts

    s = stats()
    s["teamNames"] = ["MCI", "PSG"]
    patterns = {"tactics": {
        "0": {"changes": ["Passou a defender com 5 atrás (antes eram 4)."], "positions": ["LE: sobe e apoia por fora."],
              "buildUp": {"text": "Saída de bola com 3, com o volante entre os zagueiros em 70% de 40 lances."},
              "plays": {"recentes": {"counts": {"cruzamento": 7, "entrada": 1, "chute_fora": 3}}, "partida": {"counts": {"cruzamento": 9}}, "texts": ["Chega à área mais no cruzamento (chuveirinho)."]}},
        "1": {"changes": [], "plays": {"recentes": {"counts": {}}}},
    }}
    texts = [a.text for a in tactic_alerts(s, patterns)]
    assert "MCI: Passou a defender com 5 atrás (antes eram 4)." in texts
    assert any("chuveirinho" in t for t in texts) and any("arrisca de fora" in t for t in texts)
    summary = build_summary(s, patterns, [])
    assert summary["leitura_tatica"]["MCI"]["saida_de_bola"].startswith("Saída de bola com 3")
    assert summary["leitura_tatica"]["MCI"]["mudancas_ultimos_10_min"]
