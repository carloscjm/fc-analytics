# 9. Desenvolvimento

## Ambiente

O app de verdade roda no Windows com placa NVIDIA, mas quase todo o desenvolvimento e os testes funcionam em Linux ou macOS sem GPU.

```bash
# Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install torch torchvision                  # CPU; com GPU NVIDIA: --index-url https://download.pytorch.org/whl/cu130 (driver ≥ 580) ou cu126
pip install -r requirements-dev.txt
pip install --no-deps rapidocr==3.9.2
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend
cd frontend
npm install
npm run dev     # http://localhost:5173 (proxy para o backend em :8000)
npm run build   # gera frontend/dist; o backend passa a servir a página em http://localhost:8000/
```

Na primeira subida o backend baixa o `yolo26s.pt` (pela Ultralytics) e o `football-pitch-detection.pt` (~140 MB, Google Drive do roboflow/sports). Sem internet, a detecção do campo fica indisponível e o mapa não funciona.

## Testes

`backend/tests/` (pytest). O `conftest.py` grava o SQLite numa pasta temporária (`FCA_DATA_DIR`), desliga o laço dos insights (`FCA_INSIGHTS_PUMP=0`) e aponta o Ollama para uma porta fechada (nunca chama um LLM de verdade).

| Arquivo | Cobre |
| --- | --- |
| `test_patterns.py` | linhas e formações (`split_lines`, `compute_pattern`), normalização, linha de defesa, nomes das posições, transição, `PatternStore`, `restart_clock` |
| `test_flows.py` | etapas da movimentação, identidade das posições, notas, setas de passes/cruzamentos, detecção de passes |
| `test_tactics.py` | saída de bola, jogadas com a bola (cruzamento, chute, condução), textos das posições, mudanças |
| `test_stats.py` | posse, passes, perdas, pressão, janelas, eventos, retomada do SQLite, apagar dados |
| `test_match.py` | ciclo da partida (criar, pausar, retomar, finalizar, retomada depois de reiniciar), relatório, `vivid`, `replay_patterns` |
| `test_official.py` | dados oficiais da ESPN com as fixtures `espn_scoreboard.json`/`espn_summary.json`: busca pelas siglas, busca manual, sem internet, resumo e ordem dos times |
| `test_story.py` | `Story` (oficial vale mais, frases dos gols, cards com e sem dados oficiais, todo parágrafo cita o time), quebra de linha dos cards, SVG válido com fontes, relatório com dados oficiais e cards (fixture `match_state.json`) |
| `test_insights.py` | regras de alerta, tempos de espera, resumo para o LLM, parse da resposta, agendamento (Ollama falso) |
| `test_teamnames.py` | achar o par de siglas no texto do OCR, ordem pelas cores |
| `test_pitch.py` | pontos-chave, homografia, orientação, pontos alinhados ou inconsistentes, filtro de gramado, área visível, cortes, closes, fantasmas do mapa, goleiro longe do gol |
| `test_tracking.py` | cor da camisa, calibração e autocorreção dos times, tolerância do modelo de futebol, bola estimada, pipeline com câmera em movimento (IDs e times), reinício quando o relógio volta |
| `test_ws.py` | WebSocket com detector falso: status, frames, troca de modelo, medição, ping, eventos, apagar dados, formação, `/debug`, página servida (**precisa das bibliotecas completas; sobe o `PitchDetector`, que baixa o modelo do campo na primeira vez**) |
| `test_detector.py` | YOLO de verdade numa imagem (baixa o `yolo26n.pt`) |

```bash
cd backend
pytest                                                              # tudo
pytest --ignore=tests/test_detector.py --ignore=tests/test_ws.py    # rápido, sem rede nem modelos
pytest tests/test_flows.py -k passes                                # um teste
```

O frontend não tem testes automatizados; `npm run build` roda o `tsc` com `strict`, `noUnusedLocals` e `noUnusedParameters`, que pega a maioria dos erros.

## Ver as telas sem um jogo (previews)

`tools/preview/` gera uma partida de exemplo passando posições simuladas pelo motor de verdade (`PatternStore`, `StatsTracker`), serve o painel montado com um backend falso e fotografa todas as telas:

```bash
pip install fastapi uvicorn websockets playwright   # e o Chromium do Playwright
cd frontend && npm run build && cd ..
python tools/preview/gen.py                                    # -> tools/preview/out/state.json
python -m uvicorn --app-dir tools/preview mock:app --port 8765 # deixe rodando
python tools/preview/shoot.py                                  # -> tools/preview/out/shots/*.png
```

São 26 imagens: painel inteiro, as 8 opções do campo, o campinho de cada opção, as 3 etapas da movimentação, leitura tática, estatísticas, insights, cabeçalho e relatório. Use isso para conferir mudanças visuais antes de publicar. Os números são de uma partida simulada (formações estranhas são esperadas).

## Validar na máquina de quem usa

Com o app rodando, o backend responde em `http://localhost:8000`. Os endpoints de `/debug` (veja [05-protocolo.md](05-protocolo.md#endpoints-http)) mostram o que está acontecendo sem mexer na tela. O registro fica em `%LocalAppData%\FCAnalytics\runtime\logs\backend.log`. Sinais comuns:

| Sintoma | Onde olhar | Causa provável |
| --- | --- | --- |
| Padrões param em "coletando" | `/debug/patterns` (`phaseSource` não sobe) | partida pausada/finalizada; cena sem campo (`/debug/state` → `scene`, `fit.reason`); duas abas capturando |
| IDs mudam toda hora | `/debug/state` → `tracking.avgLifeS` baixo, `cutsLastMinute` alto | cortes de câmera, replays, ou duas abas mandando frames |
| Times trocados ou "árbitro/goleiro" demais | `/debug/state` → `teams`, `roles` | calibração ruim (recalibrar), uniformes parecidos |
| Mapa torto | `/debug/snapshot.jpg` (linhas rosas fora do gramado), `fit.errorPx` | pontos do campo errados; recorte automático desligado |
| Sem análise do LLM | `/debug/insights` → `llm.state`, `lastError` | Ollama fechado, modelo não baixado, pouco jogo novo |
| Nomes dos times errados | `/debug/names` | placar não lido; use **⇄ Trocar** ou **Editar** |

## Receitas

### Novo comando do painel

1. `backend/app/main.py` → `handle_command`: novo `elif kind == "..."`, chamando o `pipeline` em `asyncio.to_thread` se for pesado, e um `broadcast` do que mudou (`stats`, `patterns`, `insights`).
2. Lógica no `Pipeline` (ou no módulo certo), com teste.
3. `frontend/src/backend.ts`: tipos novos, se a resposta mudar.
4. Mande o comando com `client.send({type: "...", ...})` (ou o `send` passado aos painéis; os tipos de comando dos painéis ficam em `MatchPanel.tsx` (`Command`) e `InsightsPanel.tsx` (`InsightCommand`)).
5. Documente em [05-protocolo.md](05-protocolo.md).

### Nova regra de alerta

`insights.evaluate_rules` (números das janelas) ou `tactic_alerts` (leitura tática). Crie um `Alert(rule, team, text, level)` com `rule` único; o tempo de espera por regra e time já vale. Texto em português, com o nome do time (`team_labels(stats)[t]`) e o número que justifica. Teste em `test_insights.py`. Atualize a tabela em [04-algoritmos.md](04-algoritmos.md#alertas-regras).

### Nova métrica da partida

1. Calcule por frame em `StatsTracker.observe` (se precisar gravar, acrescente a coluna em `FRAME_COLUMNS` **no fim**: bancos antigos não têm a coluna; trate isso com `ALTER TABLE` ou leia com cuidado).
2. Agregue em `window_stats` (e em `timeline`, se for por minuto).
3. Tipos em `backend.ts` (`WindowStats`), linha na tabela de `MatchPanel.tsx` (`rowsFor`), no relatório (`report._stats_table`) e, se fizer sentido, no resumo do LLM (`insights._window`).

### Nova leitura dos padrões

Funções puras que recebem `pattern`/`roles` normalizados (como as de `tactics.py`) e são chamadas em `PatternStore.summary` ou `team_tactics`. Lembre que `summary` roda a cada 10 s numa thread: se for pesado, use um cache como `PatternStore._flow`. Exponha no objeto `patterns`, tipe em `backend.ts`, mostre no painel e no relatório.

### Mudar um limiar

Mude a constante no topo do módulo, rode os testes do módulo e atualize o valor em `docs/04-algoritmos.md`. Muitos testes usam formações sintéticas e podem precisar de ajuste.

### Texto que a pessoa vê

Português do Brasil, frase curta e concreta, sem jargão de programação. Mensagem de erro diz o que aconteceu e o que fazer. Se o texto muda o comportamento descrito, atualize o `README.md`.

### Publicar

Veja [08-app-windows-e-release.md](08-app-windows-e-release.md#como-publicar-uma-versão). Resumo: testes, `npm run build`, previews se mexeu na tela, `VERSION` + `main.py`, push na `main`.

## Estilo de código

- **Python**: `from __future__ import annotations`, tipos em tudo, `dataclass` para estados, `numpy` vetorizado no que roda por frame, constantes nomeadas em maiúsculas no topo do módulo com comentário do porquê, docstrings e comentários em português explicando a intenção (não o óbvio). Logs com `logging.getLogger("fc-analytics")`.
- **TypeScript/React**: componentes funcionais, `strict`, sem `any` desnecessário, sem bibliotecas novas sem motivo forte. Comentários em português.
- **C#**: `Nullable` ligado, `using` explícitas, interface em código, textos em português.
- Commits em português, descrevendo o efeito para quem usa.
