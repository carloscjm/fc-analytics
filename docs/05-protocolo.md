# 5. Protocolo: WebSocket e HTTP

O painel fala com o backend por um único WebSocket em `/ws` (mesma origem da página: `ws://localhost:8000/ws`, ou `ws://localhost:5173/ws` com o proxy do Vite). Os tipos TypeScript de todas as mensagens estão em `frontend/src/backend.ts`; mantenha esse arquivo em sincronia com o backend.

## Frame binário (página → backend)

Definido em `backend/app/protocol.py` e `frontend/src/capture.ts` (`packFrame`).

| Bytes | Tipo | Conteúdo |
| --- | --- | --- |
| 0–3 | `uint32` little-endian | id do frame (sequencial na página) |
| 4–11 | `float64` little-endian | momento da captura, `performance.now()` da página, em ms |
| 12– | JPEG | imagem de até 1280 × 720 (começa com `FF D8`) |

O backend devolve `frameId` e `captureTs` na resposta, para a página medir o atraso no próprio relógio. O `captureTs / 1000` também é o relógio da sessão no pipeline (`ts`): se ele volta no tempo, a sessão recomeça.

**Uma aba por vez**: o frame só é analisado se a conexão é `app.state.capturer` (a última que mandou `reset_session`, ou a primeira a mandar frames quando não há nenhuma). Frames de outra aba recebem `{"type": "detections", "frameId", "captureTs", "conn", "stopCapture": true, "error": "..."}` e a página para de capturar.

## Mensagens do backend → página

| `type` | Quando | Conteúdo |
| --- | --- | --- |
| `hello` | ao conectar | `version`, `serverTs`, `conn` (id desta aba) |
| `status` | ao conectar e a cada mudança de modelo/estado | `state` (`pronto`, `carregando`, `medindo`, `erro`), `detail`, `model`, `models`, `imgsz`, `imgszOptions`, `device`, `footballModel`, `pitch` (`{state, error}`); ao conectar, também `patterns`, `stats` e `insights` atuais |
| `detections` | a cada frame analisado, para **todas** as abas | ver abaixo |
| `patterns` | depois de comandos que mudam os padrões | o objeto `patterns` inteiro (ver abaixo) com `type: "patterns"` |
| `stats` | depois de comandos que mudam a partida | `{stats: MatchStats}` |
| `insights` | quando o feed ou o estado do LLM mudam (checado a cada 1 s) | `items`, `llm` |
| `benchmark` | fim da medição de modelos | `rows` (`model`, `meanMs`, `p95Ms`, `fps` ou `error`), `imgsz`, `budgetMs`, `frames`, `recommended`, `device` |
| `wiped` | depois de apagar os dados | `freedBytes` |
| `pong` | resposta ao `ping` | `clientTs`, `serverTs` |
| `error` | comando inválido ou falha | `detail` |

### `detections`

```jsonc
{
  "type": "detections",
  "frameId": 123, "captureTs": 45678.9, "conn": 2,
  "width": 1280, "height": 720,
  "decodeMs": 3.1, "inferMs": 45.9, "pitchMs": 22.6, "trackMs": 27.0, "serverMs": 99.9,
  "model": "football-player-detection.pt", "imgsz": 960,
  "boxes": [ { "b": [x1, y1, x2, y2], "c": 0.87, "l": "jogador", "id": 310, "t": 0 },
             { "b": [...], "c": 0.4, "l": "bola", "id": null, "t": null, "e": false } ],
  "teams": { "state": "pronto", "progress": 1, "colors": ["#e05141", "#384f7c"], "recalibrations": 0,
             "counts": { "0": 10, "1": 10 } },
  "tracking": { "active": 21, "cutsLastMinute": 2, "newLastMinute": 30, "avgLifeS": 8.4 },
  "wide": true,
  "map": {
    "scene": "ao vivo", "pausedS": 0,
    "players": [ { "id": 310, "x": 52.3, "y": 20.1, "t": 0, "l": "jogador", "g": false, "age": 0 } ],
    "ball": { "x": 50.2, "y": 33.0, "e": false }, "trail": [[x, y], ...],
    "keypoints": 8, "fit": { "points": 8, "inliers": 8, "errorPx": 2.9, "limitPx": 14.1, "reason": "ok" },
    "kp": [[x, y, índice], ...], "cut": false,
    "view": [[x, y], ...],        // área do campo visível, em metros
    "hInv": [9 números]           // homografia campo → imagem (para desenhar as linhas sobre o vídeo)
  },
  "patterns": null,               // objeto patterns só quando mudou desde o último envio
  "stats": null,                  // MatchStats só quando mudou
  "error": "..."                  // só em falha (aí não há os outros campos)
}
```

Papéis (`l`) possíveis: `pessoa`, `jogador`, `goleiro`, `árbitro`, `árbitro/goleiro` (cor fora dos dois times), `bola`.

### Objeto `patterns`

Gerado por `PatternStore.summary` a cada 10 s.

```jsonc
{
  "options": {
    "0-ataque": {                         // também 0-defesa, 1-ataque, 1-defesa
      "team": 0, "phase": "ataque", "frames": 1787, "seconds": 457.8, "needed": 40,
      "pattern": {                        // null enquanto frames < needed
        "formation": "4-3-3", "formationSource": "auto" | "linha" | "manual",
        "roles": [ { "x": 81.7, "y": 36.4, "sx": 6.3, "sy": 5.4, "line": 2, "name": "CA", "share": 0.1 } ],
        "lineHeight": 26.8, "block": "baixo", "width": 42.7, "depth": 51.5,
        "corridors": { "esquerda": 0.35, "centro": 0.49, "direita": 0.17 },
        "heat": { "nx": 21, "ny": 14, "cell": 5, "values": [ ... nx*ny valores 0–1, linha a linha em y ] },
        "points": 14450
      },
      "backLine": { "counts": { "3": 36, "4": 32 }, "total": 94, "estimate": null, "share": 0.38 },
      "override": null                    // formação escolhida à mão, ex. "3-4-3"
    }
  },
  "phaseSource": { "bola": 3412, "avanço": 912, "sem fase": 409 },
  "team0DefendsLeft": true,
  "formationOptions": ["4-4-2", "4-3-3", ...],
  "transitions": { "0": { "moves": [ { "name": "LD", "attackName": "VOL", "attackSector": "meio",
                                       "from": [x, y], "to": [x, y], "dx": 18.6, "dy": -1.5 } ],
                          "teamShift": 10.6, "highlights": ["..."] }, "1": ... },
  "tactics": { "0": { "positions": ["..."],
                      "buildUp": { "counts": {...}, "total": 40, "main": "3 atrás", "share": 0.6, "text": "...", "recent": {...} },
                      "plays": { "partida": PlaysInfo, "recentes": PlaysInfo, "texts": ["..."] },
                      "changes": ["..."] }, "1": ... },
  "flows": { "0-ataque": { "phase": "ataque",
                           "stages": [ { "name": "Saída de bola", "height": 26.8, "frames": 596,
                                         "roles": [ { "x": 38.7, "y": 29.0, "name": "CA", "line": 2, "estimated": false } ] } ],
                           "notes": ["..."] } | null, ... },
  "ballArrows": { "0": [ { "kind": "passe" | "cruzamento", "from": [x, y], "to": [x, y], "count": 7 } ], "1": [...] }
}
```

`PlaysInfo = { counts: {cruzamento, entrada, chute_fora, chute_dentro, corta_dentro, vai_fundo}, bySide: {cruzamento|corta_dentro|vai_fundo: {esquerda, direita}} }`.

As posições em `roles`, `flows`, `transitions` e `ballArrows` estão **normalizadas** (time atacando para a direita). Os `roles` de uma mesma opção estão na mesma ordem em `pattern.roles` e em cada `flows[...].stages[i].roles`.

### Objeto `stats` (`MatchStats`)

Gerado por `StatsTracker.summary` + `Pipeline.refresh_stats` a cada 3 s.

```jsonc
{
  "matchId": 4, "startedAt": 1792584508045, "elapsedS": 1394.0,   // relógio sem as pausas
  "paused": false,                         // intervalo marcado (tecla I)
  "period": 1, "score": [1, 1],
  "events": [ { "id": 1, "t": 812, "kind": "gol", "team": 0 } ],  // gol, amarelo, vermelho, substituicao, intervalo
  "windows": { "recentes": WindowStats, "partida": WindowStats },
  "timeline": { "minutes": [1, 2, ...], "possession": [[a, b] | null, ...], "line": [[...], [...]] },
  "matchState": "livre" | "ativa" | "pausada" | "finalizada",
  "matchName": "Arsenal x Barcelona" | null,
  "pauses": [[tempoDeJogo, duração], ...], "pausedSince": 1792584600000 | null,
  "teamNames": ["ARS", "BAR"], "teamNamesSource": "placar" | "manual" | null,
  "teamColors": ["#e05141", "#384f7c"] | null,
  "storageBytes": 48200000,
  "official": OfficialInfo | null          // dados oficiais confirmados, já na ordem Time A, Time B
}
```

`OfficialInfo`: `source` (`"ESPN"`), `eventId`, `league`, `date` (ISO), `venue`, `completed`, `teams` (dois: `id`, `name`, `short`, `abbr`, `homeAway`, `score`, `color`, `stats` com `posse`, `chutes`, `chutes_no_alvo`, `escanteios`, `faltas`, `amarelos`, `vermelhos`, `impedimentos`, `defesas`, `passes`, `passes_certos`, `cruzamentos`, `cruzamentos_certos`), `goals` (`minute`, `team` 0/1, `player`, `assist`, `penalty`, `ownGoal`), `cards` (`minute`, `team`, `player`, `kind` `amarelo`/`vermelho`), `order`, `fetchedAt`.

`WindowStats` (pares `[time A, time B]`): `seconds`, `possession`, `possessionCoverage` (% do tempo com dono da bola), `tilt`, `line`, `depth`, `width`, `corridors` (`[esq, centro, dir]` por time), `passes`, `losses`, `passAccuracy`, `pressure`, `recoveries5s`, `distanceKm`.

### Objeto `insights`

```jsonc
{
  "items": [
    { "id": 1, "kind": "alerta", "wall": 1792584000000, "t": 600, "team": 1, "rule": "chuveirinho",
      "level": "info" | "atencao", "text": "..." },
    { "id": 3, "kind": "analise", "wall": ..., "t": ..., "team": null, "rule": null, "level": "info", "text": "...",
      "model": "qwen3:4b-instruct", "seconds": 11,
      "analysis": { "leitura": "...", "funcionando": [...], "espacos": [...], "sugestoes": [...], "posicoes": [...] } }
  ],                                        // últimos 40
  "llm": { "state": "pronto", "model": "qwen3:4b-instruct", "installed": [...], "recommended": [{"name", "label"}],
           "intervalS": 240, "intervalOptions": [180, 240, 300], "nextInS": 74, "lastError": null,
           "pull": { "model", "status", "completed", "total" } | null }
}
```

## Comandos da página → backend (JSON)

Todos têm `type`. Os que mudam estado respondem com um `broadcast` para todas as abas.

| `type` | Campos | Efeito | Resposta |
| --- | --- | --- | --- |
| `ping` | `clientTs` | mede o ping | `pong` só para quem pediu |
| `set_model` | `name` | troca o modelo de detecção (e salva a escolha) | `status` (carregando → pronto/erro) |
| `set_imgsz` | `imgsz` (640/960/1280) | troca a resolução | `status` |
| `benchmark` | — | mede os YOLO26 nos frames recentes | `status`, `benchmark` |
| `download_football_model` | — | baixa e ativa o modelo de futebol | `status` |
| `reset_session` | — | esta aba passa a capturar; tracking, times, bola e homografia recomeçam | — |
| `recalibrate_teams` | — | recalibra as cores dos times | — |
| `reset_patterns` | — | zera os padrões (mantém as formações manuais) | `patterns` |
| `set_formation` | `team`, `phase` (`ataque`/`defesa`), `formation` (`"3-4-3"` ou `null`) | formação manual (gravada na partida) | `patterns` |
| `create_match` | `name` (opcional) | partida nova e ativa; zera padrões, nomes e formações manuais | `stats`, `patterns` |
| `pause_match` / `resume_match` | — | pausa/retoma a gravação; pausas não contam no relógio | `stats` |
| `finish_match` | — | finaliza (para de gravar) | `stats`, `patterns` |
| `set_match_name` | `name` | renomeia a partida | `stats` |
| `new_match` | — | (antigo) partida nova no estado `livre` | `stats`, `patterns` |
| `event` | `kind` (`gol`, `amarelo`, `vermelho`, `substituicao`, `intervalo`), `team` (0/1; `null` no intervalo) | marca um evento | `stats` |
| `undo_event` | — | desfaz o último evento | `stats` |
| `wipe_data` | — | apaga todas as partidas, padrões, nomes e insights | `stats`, `patterns`, `insights`, `wiped` |
| `set_team_names` | `names: [a, b]` | nomes digitados (desliga o OCR) | `stats` |
| `swap_team_names` | — | troca qual nome é de qual camisa | `stats` |
| `auto_team_names` | — | volta a ler do placar | `stats` |
| `insight_delete` | `id` | apaga um item do feed | `insights` |
| `insights_clear` | — | apaga o feed da partida | `insights` |
| `llm_analyze_now` | — | pede uma análise já | `error` se o LLM estiver ocupado/sem modelo |
| `llm_set_model` | `model` | escolhe o modelo do Ollama | (feed muda) |
| `llm_pull` | `model` (opcional) | baixa o modelo no Ollama, com progresso em `llm.pull` | (feed muda) |
| `llm_set_interval` | `seconds` (180/240/300) | intervalo entre análises | (feed muda) |
| `official_search` | `query`, `date` (opcionais; `AAAA-MM-DD`) | procura o jogo na ESPN (sem `query`: pelas siglas e pelo nome da partida) | `official_candidates` só para quem pediu: `{candidates: [{eventId, name, date, league, status, completed, home: {name, abbr, score}, away: {...}, match}], error}` |
| `official_confirm` | `eventId`, `swap` (opcional) | baixa o resumo oficial, liga os times e grava na partida; pede uma última análise ao LLM | `stats` (com `official`) |
| `official_swap` | — | troca qual time oficial é o Time A | `stats` |
| `official_clear` | — | remove os dados oficiais da partida | `stats` |

Tipo desconhecido responde `{"type": "error", "detail": "tipo desconhecido: ..."}`.

## Endpoints HTTP

| Método e caminho | Resposta |
| --- | --- |
| `GET /health` | `{"status": "ok", "version": "0.8.1"}` (o app do Windows usa para saber se o backend subiu) |
| `GET /report.html` | relatório HTML da partida atual (`Cache-Control: no-store`); 503 sem as bibliotecas de tracking |
| `GET /cards.json` | `{"ready": true, "fontCss": "@font-face...", "cards": ["<svg ...>", ...]}`: cards do Instagram da partida atual (SVG sem fontes; `fontCss` traz as fontes em base64 uma vez) |
| `GET /debug/state` | resumo do último frame (fps, tempos, times, tracking, cena, encaixe do campo, papéis, IDs) |
| `GET /debug/snapshot.jpg` | último frame com caixas, IDs, pontos do campo e linhas projetadas |
| `GET /debug/map.png` | mapa 2D (10 px/m) com jogadores, fantasmas, bola, rastro e área visível |
| `GET /debug/patterns` | momentos, formação, linha, largura e corredores de cada opção |
| `GET /debug/stats` | `MatchStats` completo |
| `GET /debug/insights` | feed e estado do LLM |
| `GET /debug/names` | nomes atuais, nomes guardados, cores e estado do leitor do placar |
| `GET /` e arquivos | a página montada (`FCA_WEB_DIR` ou `frontend/dist`) |
