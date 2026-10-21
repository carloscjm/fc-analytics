"""Fase 5: insights e dicas.

Duas camadas:

1. **Regras (imediatas).** A cada atualização das estatísticas (3 s), limiares
   simples disparam alertas, por exemplo "linha de defesa alta há 3 minutos" ou
   "70% dos ataques pelo lado esquerdo". Cada regra tem um tempo de espera por
   time, para o mesmo alerta não se repetir a toda hora.
2. **LLM local (a cada 3 a 5 minutos).** Um resumo em JSON das estatísticas,
   formações e alertas vai para o Ollama, que roda um Qwen3 no próprio PC. A
   resposta volta em JSON estruturado (leitura do jogo, o que está funcionando,
   espaços que o adversário pode explorar e sugestões). A chamada roda numa
   thread separada, então o mapa e a detecção não param enquanto o modelo pensa.

Os insights de cada partida ficam no SQLite, junto com as estatísticas.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("fc-analytics")

TEAM = ("Time A", "Time B")
SIDES = ("esquerdo", "central", "direito")

ALERT_COOLDOWN_S = 6 * 60
MIN_RECENT_SECONDS = 90.0
FEED_LIMIT = 40

DEFAULT_MODEL = "qwen3:4b-instruct"
RECOMMENDED_MODELS = {
    "qwen3:4b-instruct": "Qwen3 4B · 2,5 GB (recomendado)",  # divide bem a placa com a detecção
    "qwen3:8b": "Qwen3 8B · 5,2 GB (texto melhor, mais pesado)",  # disputa a memória da placa com a detecção
}
DEFAULT_INTERVAL_S = 240
INTERVAL_OPTIONS = (180, 240, 300)
MIN_NEW_DATA_S = 60.0  # só chama o LLM se entrou pelo menos 1 min de jogo analisado desde a última análise
CHECK_EVERY_S = 20.0
LLM_TIMEOUT_S = 240.0


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------


@dataclass
class Alert:
    rule: str
    team: int
    text: str
    level: str = "info"  # "info" ou "atencao"


def _last_minutes(values: list[float | None], n: int) -> list[float] | None:
    tail = values[-n:]
    if len(tail) < n or any(v is None for v in tail):
        return None
    return [float(v) for v in tail]  # type: ignore[arg-type]


CHANGE_COOLDOWN_S = 15 * 60  # uma mudança de comportamento só volta a ser avisada depois de 15 min


def tactic_alerts(stats: dict[str, Any], patterns: dict[str, Any] | None) -> list[Alert]:
    """Alertas da leitura tática: mudanças nos últimos 10 min, chuveirinho e chutes de fora."""
    names = team_labels(stats)
    out: list[Alert] = []
    for key, info in ((patterns or {}).get("tactics") or {}).items():
        t = int(key)
        for change in info.get("changes", []):
            # A regra leva o começo do texto, para cada tipo de mudança ter o próprio tempo de espera.
            out.append(Alert(f"mudanca:{change.split(':')[0][:40]}", t, f"{names[t]}: {change}", "atencao"))
        recent = ((info.get("plays") or {}).get("recentes") or {}).get("counts") or {}
        crosses, entries = recent.get("cruzamento", 0), recent.get("entrada", 0)
        if crosses >= 5 and crosses >= 2 * max(entries, 1):
            out.append(Alert("chuveirinho", t, (
                f"{names[t]} está no chuveirinho: {crosses} cruzamentos na área nos últimos 10 minutos "
                f"e só {entries} entradas com a bola dominada.")))
        if recent.get("chute_fora", 0) >= 3:
            out.append(Alert("chutes_fora", t, (
                f"{names[t]} arrisca de fora: {recent['chute_fora']} chutes de fora da área nos últimos 10 minutos.")))
    return out


def team_labels(stats: dict[str, Any]) -> tuple[str, str]:
    """Nomes dos times (siglas do placar ou digitados); "Time A" e "Time B" enquanto não houver."""
    names = stats.get("teamNames") or TEAM
    return (str(names[0] or TEAM[0]), str(names[1] or TEAM[1]))


def evaluate_rules(stats: dict[str, Any]) -> list[Alert]:
    """Todos os alertas cujas condições valem agora (o tempo de espera é aplicado depois)."""
    alerts: list[Alert] = []
    recent = stats["windows"]["recentes"]
    timeline = stats["timeline"]
    seconds = recent["seconds"]
    enough = seconds >= MIN_RECENT_SECONDS
    coverage = (recent.get("possessionCoverage") or 0) / 100
    for t in (0, 1):
        name = team_labels(stats)[t]
        line = _last_minutes(timeline["line"][t], 3)
        if line and min(line) >= 45:
            alerts.append(Alert("linha_alta", t, (
                f"{name} joga com a linha de defesa alta há 3 minutos (média de {sum(line) / 3:.0f} m do próprio gol): "
                "há espaço nas costas para bola longa e contra-ataque."), "atencao"))
        if line and max(line) <= 25:
            alerts.append(Alert("bloco_baixo", t, (
                f"{name} está recuado há 3 minutos (linha a {sum(line) / 3:.0f} m do próprio gol): "
                "convida o adversário a ficar com a bola no campo de ataque."), "atencao"))
        if not enough:
            continue
        poss = recent.get("possession")
        poss_s = seconds * coverage * (poss[t] / 100) if poss else 0.0
        corridors = recent["corridors"][t]
        if corridors and poss_s >= 60:
            side = 0 if corridors[0] >= corridors[2] else 2
            if corridors[side] >= 60:
                alerts.append(Alert("corredor", t, (
                    f"{corridors[side]:.0f}% da bola do {name} no ataque passa pelo lado {SIDES[side]} dele "
                    "nos últimos 5 minutos.")))
        if poss and poss[t] >= 65 and seconds * coverage >= 90:
            alerts.append(Alert("posse", t, f"{name} domina a posse nos últimos 5 minutos ({poss[t]:.0f}%)."))
        tilt = recent.get("tilt")
        if tilt and tilt[t] >= 70:
            alerts.append(Alert("territorio", t, (
                f"{name} empurra o adversário: {tilt[t]:.0f}% do tempo com a bola no terço ofensivo nos últimos 5 minutos.")))
        accuracy = recent["passAccuracy"][t]
        if recent["losses"][t] >= 6 and accuracy is not None and accuracy <= 65:
            alerts.append(Alert("perdas", t, (
                f"{name} perde muito a bola: {recent['losses'][t]} perdas nos últimos 5 minutos "
                f"(precisão de {accuracy:.0f}% nos passes)."), "atencao"))
        rec = recent["recoveries5s"][t]
        if recent["losses"][t] >= 4 and rec is not None and rec >= 50:
            alerts.append(Alert("pressao", t, (
                f"{name} pressiona bem depois de perder: recupera a bola em até 5 s em {rec:.0f}% das perdas.")))
        depth = recent["depth"][t]
        if depth is not None and depth >= 48:
            alerts.append(Alert("espacado", t, (
                f"{name} está espaçado: {depth:.0f} m entre o último defensor e o atacante mais avançado; "
                "o meio-campo fica aberto."), "atencao"))
    return alerts


# ---------------------------------------------------------------------------
# Resumo para o LLM
# ---------------------------------------------------------------------------


def _pair(values: list[Any] | None, names: tuple[str, str] = TEAM) -> dict[str, Any] | None:
    if values is None:
        return None
    return {names[t]: (round(v) if isinstance(v, (int, float)) else v) for t, v in enumerate(values)}


def _window(w: dict[str, Any], names: tuple[str, str] = TEAM) -> dict[str, Any]:
    corridors = {}
    for t in (0, 1):
        c = w["corridors"][t]
        corridors[names[t]] = None if c is None else {"esquerda": round(c[0]), "centro": round(c[1]), "direita": round(c[2])}
    return {
        "minutos_de_jogo_analisados": round(w["seconds"] / 60, 1),
        "posse_pct": _pair(w["possession"], names),
        "dominio_territorial_pct": _pair(w["tilt"], names),
        "passes": _pair(w["passes"], names),
        "precisao_passes_pct": _pair(w["passAccuracy"], names),
        "perdas_de_bola": _pair(w["losses"], names),
        "recupera_em_5s_pct": _pair(w["recoveries5s"], names),
        "linha_defesa_m_do_proprio_gol": _pair(w["line"], names),
        "distancia_defesa_ataque_m": _pair(w["depth"], names),
        "largura_m": _pair(w["width"], names),
        "por_onde_ataca_pct": corridors,
    }


def _recent_window(w: dict[str, Any], names: tuple[str, str] = TEAM) -> dict[str, Any]:
    """Com pouco jogo analisado nos últimos 5 min, os números enganam: o modelo recebe só um aviso."""
    if w["seconds"] < MIN_RECENT_SECONDS:
        return {
            "minutos_de_jogo_analisados": round(w["seconds"] / 60, 1),
            "aviso": "pouco jogo analisado nos últimos 5 minutos; não tire conclusões desta janela, use a partida inteira",
        }
    return _window(w, names)


def build_summary(stats: dict[str, Any], patterns: dict[str, Any] | None, alerts: list[str]) -> dict[str, Any]:
    names = team_labels(stats)
    labels = {"gol": "gol", "amarelo": "cartão amarelo", "vermelho": "cartão vermelho", "substituicao": "substituição"}
    events = [
        {"minuto": int(e["t"] // 60) + 1, "evento": labels.get(e["kind"], e["kind"]), "time": names[e["team"]] if e["team"] is not None else None}
        for e in stats["events"]
        if e["kind"] != "intervalo"
    ]
    formations: dict[str, Any] = {}
    if patterns:
        for key, option in patterns.get("options", {}).items():
            pattern = option.get("pattern")
            if not pattern:
                continue
            team, phase = key.split("-")
            formations[f"{names[int(team)]} {'atacando' if phase == 'ataque' else 'defendendo'}"] = {
                "formacao": pattern.get("formation"),
                "formacao_definida_por": {
                    "manual": "quem assiste (escolhida à mão)",
                    "linha": "contagem da linha de defesa",
                }.get(pattern.get("formationSource"), "posições médias"),
                "linha_defesa_m": pattern.get("lineHeight"),
                "largura_m": pattern.get("width"),
            }
    return {
        "minuto_no_app": int(stats["elapsedS"] // 60) + 1,
        "tempo": f"{stats['period']}º tempo",
        "placar": f"{names[0]} {stats['score'][0]} x {stats['score'][1]} {names[1]}",
        "eventos": events,
        "ultimos_5_minutos": _recent_window(stats["windows"]["recentes"], names),
        "partida_inteira": _window(stats["windows"]["partida"], names),
        "padroes": formations,
        "movimentos_da_defesa_para_o_ataque": {
            names[int(t)]: [h for h in (tr or {}).get("highlights", [])[:4]]
            for t, tr in ((patterns or {}).get("transitions") or {}).items()
            if tr
        },
        "leitura_tatica": {
            names[int(t)]: {
                "posicoes": info.get("positions", [])[:9],
                "saida_de_bola": (info.get("buildUp") or {}).get("text"),
                "bola_no_ataque": (info.get("plays") or {}).get("texts", []),
                "jogadas_na_partida": ((info.get("plays") or {}).get("partida") or {}).get("counts"),
                "mudancas_ultimos_10_min": info.get("changes", []),
            }
            for t, info in ((patterns or {}).get("tactics") or {}).items()
        },
        "alertas_recentes": alerts[-6:],
    }


SYSTEM_PROMPT = (
    "Você é um analista tático de futebol. Recebe números aproximados, medidos por visão computacional numa "
    "transmissão de TV (a câmera não mostra o campo todo). Escreva em português do Brasil, com frases curtas e "
    "concretas. Use só o que está nos dados, cite números quando ajudarem e não invente jogadores, nomes ou "
    "lances. Os times se chamam {time_a} e {time_b}. Esquerda e direita são do ponto de vista do time que ataca.\n"
    "Significado dos campos:\n"
    "- posse_pct: quanto tempo cada time ficou com a bola.\n"
    "- dominio_territorial_pct: quanto tempo a bola ficou no terço ofensivo de cada time.\n"
    "- linha_defesa_m_do_proprio_gol: distância da defesa até o próprio gol; maior = linha mais alta, menor = bloco baixo.\n"
    "- distancia_defesa_ataque_m: distância entre o último defensor e o atacante mais avançado; maior = time mais "
    "espaçado, menor = time compacto.\n"
    "- largura_m: distância entre os jogadores mais abertos; maior = time mais aberto.\n"
    "- por_onde_ataca_pct: por qual lado a bola anda quando o time ataca. NÃO é espaço deixado.\n"
    "- recupera_em_5s_pct: em quantas perdas de bola o time recuperou em até 5 segundos.\n"
    "Se uma janela tiver um aviso, não use os números dela."
)

USER_PROMPT = (
    "Dados da partida até agora (JSON):\n{data}\n\n"
    "Responda só com JSON, com estes campos:\n"
    "- leitura: 2 a 3 frases sobre o momento do jogo nos últimos minutos, comparando com a partida inteira.\n"
    "- funcionando: até 3 itens, cada um dizendo o que está dando certo e para qual time.\n"
    "- espacos: até 3 itens, cada um dizendo onde um time deixa espaço (por exemplo linha alta = espaço nas costas, "
    "time espaçado = meio aberto, ataque sempre pelo mesmo lado = o outro lado livre) e como o outro pode explorar.\n"
    "- sugestoes: até 3 dicas práticas, cada uma dizendo para qual time (por exemplo trocar o lado do ataque, "
    "baixar ou subir o bloco, pressionar mais depois de perder a bola).\n"
    "- posicoes: até 4 itens sobre o comportamento das posições e das jogadas, usando leitura_tatica: laterais "
    "(apoiam por fora ou por dentro), volantes (caem na saída de bola?), meias (entre as linhas, abertos ou recuados), "
    "pontas (abrem ou cortam para dentro), centroavante, saída de bola e como chegam à área (cruzamentos, entradas "
    "trabalhadas, chutes de fora). Diga o time em cada item e destaque mudanças dos últimos 10 minutos.\n"
    "Cada item deve ter uma frase só, sem repetir o mesmo número em itens diferentes e sem dicas que se contradizem."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "leitura": {"type": "string"},
        "funcionando": {"type": "array", "items": {"type": "string"}},
        "espacos": {"type": "array", "items": {"type": "string"}},
        "sugestoes": {"type": "array", "items": {"type": "string"}},
        "posicoes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["leitura", "funcionando", "espacos", "sugestoes", "posicoes"],
}


def parse_analysis(content: str) -> dict[str, Any]:
    """Valida a resposta do modelo; aceita JSON com texto em volta."""
    text = content.strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("o modelo não respondeu em JSON")
        text = text[start : end + 1]
    data = json.loads(text)
    leitura = str(data.get("leitura", "")).strip()
    if not leitura:
        raise ValueError("resposta sem a leitura do jogo")

    def items(key: str) -> list[str]:
        raw = data.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(v).strip()[:400] for v in raw if str(v).strip()][:3]

    return {
        "leitura": leitura[:800],
        "funcionando": items("funcionando"),
        "espacos": items("espacos"),
        "sugestoes": items("sugestoes"),
        "posicoes": items("posicoes")[:4] if data.get("posicoes") else [],
    }


# ---------------------------------------------------------------------------
# Cliente do Ollama
# ---------------------------------------------------------------------------


class Ollama:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        if not self.base_url.startswith("http"):
            self.base_url = f"http://{self.base_url}"

    def _request(self, path: str, body: dict[str, Any] | None = None, timeout: float = 5.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
        )
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (endereço local fixo)

    def models(self) -> list[str]:
        with self._request("/api/tags", timeout=3.0) as res:
            return sorted(m["name"] for m in json.load(res).get("models", []))

    def chat(self, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "format": schema,
            "keep_alive": "1m",  # libera a memória da placa logo depois, para a detecção
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        with self._request("/api/chat", body, timeout=LLM_TIMEOUT_S) as res:
            return json.load(res)["message"]["content"]

    def pull(self, model: str, progress: Callable[[dict[str, Any]], None]) -> None:
        with self._request("/api/pull", {"model": model, "stream": True}, timeout=3600) as res:
            for line in res:
                if line.strip():
                    message = json.loads(line)
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    progress(message)


def has_model(installed: list[str], model: str) -> bool:
    names = set(installed)
    return model in names or f"{model}:latest" in names


# ---------------------------------------------------------------------------
# Motor de insights
# ---------------------------------------------------------------------------


@dataclass
class LlmState:
    state: str = "verificando"  # verificando, desligado, sem modelo, baixando, pronto, analisando, erro
    model: str = DEFAULT_MODEL
    installed: list[str] = field(default_factory=list)
    interval_s: int = DEFAULT_INTERVAL_S
    last_error: str | None = None
    pull: dict[str, Any] | None = None
    next_at: float = 0.0
    last_seconds: float = 0.0  # segundos analisados da partida na última análise
    busy: bool = False
    checked_at: float = 0.0


class InsightEngine:
    """Alertas por regra e análises do LLM de uma partida."""

    def __init__(
        self,
        store: Any = None,
        ollama: Ollama | None = None,
        settings_path: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.ollama = ollama or Ollama()
        self.clock = clock
        self._lock = threading.Lock()
        self.settings_path = settings_path
        self.llm = LlmState()
        self._load_settings()
        self.match_id: int | None = None
        self.items: list[dict[str, Any]] = []
        self.cooldown: dict[tuple[str, int], float] = {}
        self.version = 0
        self.latest_stats: dict[str, Any] | None = None
        self.latest_patterns: dict[str, Any] | None = None

    # ---- configurações ----

    def _load_settings(self) -> None:
        if not self.settings_path or not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.llm.model = str(data.get("model") or DEFAULT_MODEL)
            if int(data.get("interval_s", 0)) in INTERVAL_OPTIONS:
                self.llm.interval_s = int(data["interval_s"])
        except (OSError, ValueError):
            log.warning("configurações do LLM ilegíveis; usando as padrão")

    def _save_settings(self) -> None:
        if not self.settings_path:
            return
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps({"model": self.llm.model, "interval_s": self.llm.interval_s}), encoding="utf-8"
            )
        except OSError:
            log.warning("não foi possível salvar as configurações do LLM")

    def set_model(self, model: str) -> None:
        with self._lock:
            self.llm.model = model
            self.llm.state = "pronto" if has_model(self.llm.installed, model) else "sem modelo"
            self.version += 1
        self._save_settings()

    def set_interval(self, seconds: int) -> None:
        if seconds not in INTERVAL_OPTIONS:
            raise ValueError("intervalo inválido")
        with self._lock:
            self.llm.interval_s = seconds
            self.llm.next_at = min(self.llm.next_at, self.clock() + seconds) if self.llm.next_at else 0.0
            self.version += 1
        self._save_settings()

    # ---- partida ----

    def bind_match(self, match_id: int) -> None:
        """Troca de partida: carrega o feed gravado (ou começa vazio)."""
        with self._lock:
            if match_id == self.match_id:
                return
            self.match_id = match_id
            self.items = self.store.load_insights(match_id) if self.store else []
            self.cooldown = {}
            self.llm.last_seconds = 0.0
            self.llm.next_at = 0.0
            self.version += 1

    def _add(self, item: dict[str, Any]) -> None:
        if self.store and self.match_id is not None:
            item["id"] = self.store.add_insight(self.match_id, item)
        else:
            item["id"] = len(self.items) + 1
        self.items.append(item)
        self.version += 1

    def forget(self) -> None:
        """Depois de apagar todos os dados: feed vazio e nenhuma partida carregada."""
        with self._lock:
            self.items = []
            self.match_id = None
            self.cooldown = {}
            self.latest_stats = None
            self.llm.last_seconds = 0.0
            self.llm.next_at = 0.0
            self.version += 1

    # ---- limpar o feed ----

    def remove(self, item_id: int) -> bool:
        """Apaga um item do feed (alerta ou análise). O tempo de espera dos alertas continua valendo."""
        with self._lock:
            before = len(self.items)
            self.items = [i for i in self.items if i.get("id") != item_id]
            if len(self.items) == before:
                return False
            if self.store and self.match_id is not None:
                self.store.delete_insights(self.match_id, [item_id])
            self.version += 1
            return True

    def clear(self) -> int:
        """Apaga o feed inteiro da partida atual."""
        with self._lock:
            removed = len(self.items)
            self.items = []
            if self.store and self.match_id is not None:
                self.store.delete_insights(self.match_id)
            self.version += 1
            return removed

    # ---- a cada atualização das estatísticas ----

    def on_stats(self, stats: dict[str, Any], patterns: dict[str, Any] | None) -> None:
        self.bind_match(stats["matchId"])
        now = self.clock()
        with self._lock:
            self.latest_stats, self.latest_patterns = stats, patterns
            if not stats.get("paused"):
                for alert in evaluate_rules(stats) + tactic_alerts(stats, patterns):
                    key = (alert.rule, alert.team)
                    wait = CHANGE_COOLDOWN_S if alert.rule.startswith("mudanca") else ALERT_COOLDOWN_S
                    if now - self.cooldown.get(key, -1e9) < wait:
                        continue
                    self.cooldown[key] = now
                    self._add({
                        "kind": "alerta", "wall": round(now * 1000), "t": stats["elapsedS"], "team": alert.team,
                        "rule": alert.rule, "level": alert.level, "text": alert.text,
                    })
        self._maybe_check(now)
        self._maybe_analyze(now)

    def tick(self) -> None:
        """Chamado a cada poucos segundos, mesmo sem captura: confere o Ollama e a hora da próxima análise."""
        now = self.clock()
        self._maybe_check(now)
        self._maybe_analyze(now)

    # ---- Ollama ----

    def _maybe_check(self, now: float, force: bool = False) -> None:
        with self._lock:
            if not force and (now - self.llm.checked_at < CHECK_EVERY_S or self.llm.state in ("baixando", "analisando")):
                return
            self.llm.checked_at = now
        threading.Thread(target=self.check, daemon=True).start()

    def check(self) -> None:
        try:
            installed = self.ollama.models()
        except (urllib.error.URLError, OSError, ValueError):
            with self._lock:
                if self.llm.state not in ("baixando", "analisando"):
                    self.llm.state = "desligado"
                self.llm.installed = []
                self.version += 1
            return
        with self._lock:
            changed = installed != self.llm.installed
            self.llm.installed = installed
            if self.llm.state not in ("baixando", "analisando"):
                new_state = "pronto" if has_model(installed, self.llm.model) else "sem modelo"
                changed = changed or new_state != self.llm.state
                self.llm.state = new_state
            if changed:
                self.version += 1

    def _maybe_analyze(self, now: float) -> None:
        with self._lock:
            stats = self.latest_stats
            if self.llm.state != "pronto" or self.llm.busy or stats is None or stats.get("paused"):
                return
            if not self.llm.next_at:
                self.llm.next_at = now + 60  # primeira análise 1 min depois de o app subir
                self.version += 1
                return
            if now < self.llm.next_at:
                return
            analyzed = stats["windows"]["partida"]["seconds"]
            if analyzed - self.llm.last_seconds < MIN_NEW_DATA_S:
                self.llm.next_at = now + 30  # pouco jogo novo: tenta de novo em 30 s
                return
        self.analyze_now()

    def analyze_now(self) -> bool:
        with self._lock:
            if self.llm.busy or self.latest_stats is None:
                return False
            if not has_model(self.llm.installed, self.llm.model):
                self.llm.last_error = f"O modelo {self.llm.model} ainda não foi baixado."
                self.version += 1
                return False
            self.llm.busy = True
            self.llm.state = "analisando"
            self.version += 1
            stats, patterns = self.latest_stats, self.latest_patterns
            alerts = [i["text"] for i in self.items if i["kind"] == "alerta"]
            model = self.llm.model
        threading.Thread(target=self._analyze, args=(stats, patterns, alerts, model), daemon=True).start()
        return True

    def _analyze(self, stats: dict[str, Any], patterns: dict[str, Any] | None, alerts: list[str], model: str) -> None:
        started = self.clock()
        summary = build_summary(stats, patterns, alerts)
        error = None
        analysis = None
        try:
            content = self.ollama.chat(
                model, SYSTEM_PROMPT.format(time_a=team_labels(stats)[0], time_b=team_labels(stats)[1]), USER_PROMPT.format(data=json.dumps(summary, ensure_ascii=False)), RESPONSE_SCHEMA
            )
            analysis = parse_analysis(content)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            error = f"Falha na análise do LLM: {exc}"
            log.warning(error)
        now = self.clock()
        with self._lock:
            self.llm.busy = False
            self.llm.state = "pronto"
            self.llm.next_at = now + self.llm.interval_s
            self.llm.last_error = error
            if analysis is not None and stats["matchId"] == self.match_id:
                self.llm.last_seconds = stats["windows"]["partida"]["seconds"]
                self._add({
                    "kind": "analise", "wall": round(now * 1000), "t": stats["elapsedS"], "team": None,
                    "rule": None, "level": "info", "text": analysis["leitura"], "analysis": analysis,
                    "model": model, "seconds": round(now - started, 1),
                })
            self.version += 1

    def pull(self, model: str | None = None) -> bool:
        model = model or self.llm.model
        with self._lock:
            if self.llm.state == "baixando":
                return False
            self.llm.state = "baixando"
            self.llm.pull = {"model": model, "status": "começando", "completed": 0, "total": 0}
            self.llm.last_error = None
            self.version += 1

        def progress(message: dict[str, Any]) -> None:
            with self._lock:
                pull = self.llm.pull or {}
                pull["status"] = message.get("status", pull.get("status"))
                if message.get("total"):
                    pull["total"] = message["total"]
                    pull["completed"] = message.get("completed", 0)
                self.llm.pull = pull
                self.version += 1

        def work() -> None:
            try:
                self.ollama.pull(model, progress)
                error = None
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
                error = f"Falha ao baixar {model}: {exc}"
                log.warning(error)
            with self._lock:
                self.llm.pull = None
                self.llm.state = "verificando"
                self.llm.last_error = error
                self.version += 1
            self.check()

        threading.Thread(target=work, daemon=True).start()
        return True

    # ---- para a página ----

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        with self._lock:
            llm = self.llm
            return {
                "items": [dict(i) for i in self.items[-FEED_LIMIT:]],
                "llm": {
                    "state": llm.state,
                    "model": llm.model,
                    "installed": list(llm.installed),
                    "recommended": [{"name": k, "label": v} for k, v in RECOMMENDED_MODELS.items()],
                    "intervalS": llm.interval_s,
                    "intervalOptions": list(INTERVAL_OPTIONS),
                    "nextInS": max(0, round(llm.next_at - now)) if llm.next_at and llm.state == "pronto" else None,
                    "lastError": llm.last_error,
                    "pull": dict(llm.pull) if llm.pull else None,
                },
            }
