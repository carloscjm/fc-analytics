# 3. Backend (Python)

Pasta `backend/`. Python 3.12, FastAPI, uvicorn. Ponto de entrada: `uvicorn app.main:app`.

## Dependências

`backend/requirements.txt` (o PyTorch é instalado antes, à parte, do índice oficial com a versão de CUDA certa):

| Pacote | Uso |
| --- | --- |
| `fastapi`, `uvicorn[standard]` | servidor HTTP e WebSocket |
| `numpy`, `opencv-python` | imagens, homografia, geometria |
| `ultralytics` | YOLO (detecção de jogadores/bola e pontos do campo) |
| `supervision` | estrutura `Detections` que o tracker usa |
| `trackers` | BoT-SORT (Roboflow) |
| `gdown` | baixar os modelos do Google Drive do projeto roboflow/sports |
| `onnxruntime`, `pyclipper`, `shapely`, `omegaconf`, `colorlog`, `pyyaml` | dependências do RapidOCR |
| `rapidocr==3.9.2` | **instalado com `--no-deps`** (senão traz o `opencv-python-headless`, que briga com o `opencv-python`) |
| `scipy` | vem com o ultralytics; usado no casamento de posições (`linear_sum_assignment`) |

`requirements-dev.txt` acrescenta `pytest` e `httpx`.

## Variáveis de ambiente

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `FCA_DATA_DIR` | `backend/data` | pasta do `partidas.sqlite` e do `llm.json` |
| `FCA_MODELS_DIR` | `backend/models` | pasta dos modelos `.pt` e do `modelo-escolhido.txt` |
| `FCA_WEB_DIR` | `frontend/dist` (se existir) | pasta da página servida em `/` |
| `FCA_MODEL` | escolha salva, senão `yolo26s.pt` | força o modelo de detecção ao subir |
| `FCA_IMGSZ` | `960` | resolução da inferência (640, 960 ou 1280) |
| `FCA_INSIGHTS_PUMP` | `1` | `0` desliga o laço dos insights (usado nos testes) |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | endereço do Ollama |

## Módulos

### `main.py`: aplicação, WebSocket e endpoints

- `VERSION`: versão mostrada em `/health` e no relatório. **Mantenha igual ao arquivo `VERSION` da raiz.**
- `lifespan`: cria o `Detector`, o `Pipeline` (se faltar biblioteca de tracking, segue só com detecção e mostra `setup_warning`) e o `PitchDetector`; carrega o modelo em segundo plano (`warm`); inicia o `insights_pump`.
- `ws_endpoint` / `_serve`: cada conexão recebe um `conn`, um `hello` e um `status` (com padrões, estatísticas e insights atuais). Mensagens binárias vão para `handle_frame`; texto JSON vai para `handle_command`.
- `handle_frame`: decodifica, aplica a regra de **uma aba capturando por vez** (`app.state.capturer`), roda detector, campo e pipeline em threads, monta a mensagem `detections` e faz `broadcast`.
- `handle_command`: todos os comandos do painel. A lista completa, com o formato de cada um, está em [05-protocolo.md](05-protocolo.md).
- `insights_pump`: a cada 1 s manda o feed de insights para as abas se ele mudou; a cada 5 s chama `InsightEngine.tick` (só com a partida gravando).
- Endpoints HTTP: `/health`, `/debug/*`, `/report.html`. A página é montada por último em `/` (`StaticFiles`), para não esconder as outras rotas.
- `send` / `broadcast`: envio com trava por conexão; conexões mortas saem de `app.state.clients`.

### `protocol.py`: formato do frame binário

`parse_frame(data) -> FramePacket(frame_id, capture_ts, jpeg)` e `build_frame(...)`. Cabeçalho de 12 bytes (`<Id`: uint32 + float64, little-endian) seguido do JPEG. Erros viram `FrameFormatError`.

### `detector.py`: YOLO de jogadores e bola

- `Detector`: carrega um modelo por vez (`set_model`, guarda a escolha em `modelo-escolhido.txt`), roda em `cuda:0` com meia precisão quando há GPU, senão CPU.
- Modelos: os oficiais `yolo26n/s/m/l/x.pt` (COCO; filtra `person` → `"pessoa"` e `sports ball` → `"bola"`) e qualquer `.pt` em `MODELS_DIR` (por exemplo `football-player-detection.pt`, com `player` → `"jogador"`, `goalkeeper` → `"goleiro"`, `referee` → `"árbitro"`, `ball` → `"bola"`). O `football-pitch-detection.pt` não aparece na lista (não é detector de jogadores).
- `download_football_model`: baixa o modelo de futebol do Google Drive do roboflow/sports (`gdown`), só quando a pessoa pede.
- `benchmark`: mede cada tamanho do YOLO26 nos frames recentes e recomenda o maior com p95 abaixo de `BUDGET_MS = 50`.
- Constantes: `conf = 0.25`, `IMGSZ_OPTIONS = [640, 960, 1280]`.

### `pitch.py`: campo, homografia, cortes e closes

- Medidas oficiais (`LENGTH = 105`, `WIDTH = 68`, áreas, círculo) e `keypoint_positions()`: os 32 pontos-chave na ordem do modelo do roboflow/sports.
- `PitchDetector`: modelo YOLOv8 pose `football-pitch-detection.pt` (baixado do Google Drive na primeira vez, ~140 MB), `PITCH_IMGSZ = 640`, pontos com confiança ≥ `KEYPOINT_MIN_CONF = 0.5`. Estados: `ausente`, `baixando`, `carregando`, `pronto`, `erro`.
- `keypoints_on_grass`: descarta pontos cuja vizinhança não é gramado (faixas pretas, placar, menus).
- `fit_homography`, `orient`, `plausible`, `HomographyTracker`: imagem → metros com RANSAC, checagens de qualidade, orientação e suavização. Detalhes em [04-algoritmos.md](04-algoritmos.md#campo-e-homografia).
- `LAST_FIT`: diagnóstico do último encaixe (pontos, inliers, erro, motivo da recusa), exposto em `/debug/state`.
- `visible_area(h, w, h)`: polígono, em metros, da parte do campo que a câmera mostra.
- `CutDetector`: corte de câmera pela correlação de histogramas entre frames (`CUT_CORRELATION = 0.55`).
- `is_close_up`: alguém com altura ≥ 25% da imagem = close.

### `pipeline.py`: o processamento de cada frame

`Pipeline` junta tudo por frame e guarda os objetos de longa duração:

| Atributo | Classe | Vida |
| --- | --- | --- |
| `patterns` | `PatternStore` | até "Zerar padrões", criar partida ou apagar dados |
| `stats` | `StatsTracker` | a partida atual (no SQLite) |
| `insights` | `InsightEngine` | feed da partida atual |
| `name_reader`, `team_names` | `TeamNameReader`, `TeamNames` | a partida atual |
| `tracker`, `teams`, `ball`, `homography`, `map`, `cuts` | BoT-SORT, `TeamClassifier`, `BallTracker`, `HomographyTracker`, `FieldMap`, `CutDetector` | a sessão (zeram em `reset()`) |

Funções principais:

- `process(image, boxes, ts, keypoints)`: se `ts` voltou no tempo, chama `reset()`; depois `_process`.
- `_process`: corte de câmera → tracking (`make_tracker`, BoT-SORT ajustado para ~7 fps e jogadores pequenos) → vida de cada ID (`TrackLife`, rótulo mais votado) → cor da camisa e voto de time → papéis (`"jogador"`, `"árbitro/goleiro"`, `"goleiro"`...) → bola → homografia → `FieldMap` → OCR do placar → `patterns.observe` e `stats.observe` (só com `view.fresh` e `stats.recording`) → agenda os resumos.
- `_on_cut`: novo tracker, IDs continuam a partir do maior já usado (`id_offset`), bola e homografia zeradas, fantasmas do mapa esquecem os IDs.
- `_maybe_summarize` (10 s) e `_maybe_stats` (3 s): resumos em segundo plano, agendados pelo relógio do servidor (`time.monotonic()`).
- Partida: `create_match`, `pause_match`, `resume_match`, `finish_match`, `new_match` (antigo), `wipe_all`.
- `rebuild_patterns` + `replay_patterns`: ao subir, refaz os padrões passando de novo pelas posições gravadas da partida atual (a área da câmera não é gravada, então as contagens da linha de defesa não voltam). Durante o replay (`replaying = True`) os frames ao vivo não entram nos padrões.
- Nomes: `team_labels`, `set_team_names`, `swap_team_names`, `auto_team_names`, `_update_names` (callback do OCR).
- Formação manual: `set_formation(team, phase, text)` grava em `match_meta["formations"]`; `_load_overrides` recarrega.
- Cores: `_match_colors` guarda as cores da calibração em `match_meta["colors"]` e as devolve quando não há captura.
- `report_html(version)`: monta o relatório com estatísticas, padrões recalculados e o feed inteiro.

### `teams.py`: times pela cor da camisa

`jersey_feature` (cor mediana do tronco em Lab, sem gramado), `kmeans`, `fit_teams`, `TeamModel.classify` e `TeamClassifier` (calibração, votos por ID, autocorreção). Detalhes em [04-algoritmos.md](04-algoritmos.md#times-pela-cor-da-camisa).

### `ball.py`: bola

`BallTracker.update(candidates, ts)`: escolhe a candidata mais perto da posição prevista; se a bola some por até `MAX_MISSING_SECONDS = 0.6`, estima pela velocidade (`estimated = True`, aparece como "bola?").

### `fieldmap.py`: mapa em metros

`FieldMap.update(h, boxes, ts, scene)` e `snapshot(ts)`. Pés de cada jogador (centro de baixo da caixa) levados para metros, suavização (`POSITION_SMOOTHING = 0.6`), fantasmas de até `GHOST_SECONDS = 4` s, rastro da bola de 3 s, `fix_goalkeepers` (goleiro a mais de 30 m do gol vira jogador; um goleiro por time), quem está a mais de `PLAYER_OUTSIDE_MARGIN_M = 1.5` m fora das linhas sai do mapa.

Cada jogador no `snapshot`: `{id, x, y, t (time), l (papel), g (fantasma), age}`.

### `patterns.py`: padrões dos times

`PatternStore` acumula, por `(time, fase)`, as posições normalizadas de cada momento (até `MAX_FRAMES = 12000`), decide quem ataca (posse), de que lado cada time defende, conta a linha de defesa, registra saídas de bola, jogadas com a bola (`BallPlays`) e passes. `summary(now)` devolve o objeto `patterns` que vai para a página (formato em [05-protocolo.md](05-protocolo.md#objeto-patterns)). Funções puras: `normalize`, `split_lines`, `compute_pattern`, `name_roles`, `back_line_members`, `back_line_summary`, `parse_formation`, `transition`, `highlights`, `team_tactics`. Detalhes em [04-algoritmos.md](04-algoritmos.md).

Constantes principais: `POSSESSION_RADIUS_M = 4`, `POSSESSION_CONFIRM_FRAMES = 2`, `POSSESSION_MEMORY_S = 3`, `TILT_MIN_DIFF_M = 6`, `MIN_PLAYERS_PER_FRAME = 5`, `GHOST_MAX_AGE_S = 2`, `MIN_FRAMES_FOR_PATTERN = 40`, `ROLES = 10`, `SIDE_HALF_LIFE_S = 120`, `HEAT_CELL_M = 5`, `FORMATIONS` (15 formações com custo de raridade), `FORMATION_PRIOR_WEIGHT = 0.12`, `BACK_LINE_BAND_M = 5`, `BACK_LINE_MIN_WIDTH_M = 22`, `BACK_LINE_COVERAGE = 0.9`, `BACK_LINE_MIN_FRAMES = 30`, `BACK_LINE_MIN_SHARE = 0.45`, `FLOW_EVERY_FRAMES = 200`, `PASS_OWNER_RADIUS_M = 2.5`, `PASS_MAX_GAP_S = 4`, `PASS_MIN_M = 8`.

### `flows.py`: movimentação e setas

- `team_flow(frames, pattern, phase)`: divide os momentos em três etapas pela altura do time e segue cada uma das 10 posições pelas etapas. Devolve `{phase, stages: [{name, height, frames, roles: [{x, y, name, line, estimated}]}], notes}`.
- `flow_notes`: frases sobre a última linha em cada etapa, quanto o time sobe/recua e as posições que mais se destacam.
- `ball_arrows(passes, crosses, team)`: até 3 passes repetidos entre zonas diferentes (≥ 3 vezes) e um cruzamento médio por lado (≥ 2 vezes).

### `tactics.py`: leitura tática

`classify_build_up`, `build_up_summary`, `build_up_text`, `BallPlays` (cruzamento, entrada, chutes, conduções), `plays_summary`, `plays_texts`, `role_texts`, `match_to_reference`, `change_texts`. `RECENT_S = 600` define "últimos 10 minutos".

### `stats.py`: partida e estatísticas

- `MatchStore`: SQLite (WAL) com gravação em lote; partidas, frames, posições, jogadas, eventos, insights, metadados. Esquema em [06-dados.md](06-dados.md).
- `StatsTracker`: ciclo da partida (`create_match`, `pause`, `resume`, `finish`, `set_name`, `clock`, `recording`), eventos manuais (`add_event`, `undo_event`), `observe` de cada momento (posse pelo dono da bola, passes, perdas, pressão, forma do time, distância), `summary`.
- `window_stats` e `timeline`: métricas de uma janela e por minuto.
- Retoma a última partida se ela teve dados há menos de `STALE_MATCH_S = 4 h`.

### `insights.py`: alertas e LLM

- `evaluate_rules(stats)` e `tactic_alerts(stats, patterns)`: alertas; `ALERT_COOLDOWN_S = 6 min` por regra e time, `CHANGE_COOLDOWN_S = 15 min` para mudanças.
- `build_summary`: JSON enviado ao LLM.
- `SYSTEM_PROMPT`, `USER_PROMPT`, `RESPONSE_SCHEMA` (`leitura`, `funcionando`, `espacos`, `sugestoes`, `posicoes`), `parse_analysis`.
- `Ollama`: `/api/tags`, `/api/chat` (`think: false`, `format: schema`, `keep_alive: "1m"`, `temperature 0.3`, `num_ctx 8192`, timeout 240 s), `/api/pull`.
- `InsightEngine`: feed da partida (no SQLite), estado do LLM (`verificando`, `desligado`, `sem modelo`, `baixando`, `pronto`, `analisando`, `erro`), agendamento, configurações em `llm.json` (`model`, `interval_s`).

### `teamnames.py`: nomes pelo placar

`TeamNameReader` lê a faixa de cima da imagem (`BAND_TOP = 0.28`) com RapidOCR numa thread, acha um par de siglas (`find_pair`), vota (`VOTES_TO_CONFIRM = 3`) e decide qual sigla é de qual camisa (`TeamNames.ordered`, pelas cores dos retângulos ao lado das siglas quando dá). `clean_names` valida nomes digitados.

### `report.py`: relatório HTML

`build_report(stats, patterns, insights, colors, version)` devolve uma página HTML única (CSS embutido, campinhos e gráfico de posse em SVG). `vivid(color)` deixa a cor da camisa mais saturada; a mesma regra existe no frontend (`colors.ts`).

### `check_env.py`

Script para a pessoa conferir o ambiente (Python, GPU, Node, Ollama). Não é importado pelo app.
