# 4. Algoritmos

Como cada análise é calculada, com os limiares do código. Todos os valores vêm de constantes nos módulos citados; mude lá e atualize aqui.

## Sistema de coordenadas

- **Imagem:** pixels do frame enviado (até 1280 × 720, já recortado na área do vídeo).
- **Campo (metros):** `x` de 0 a 105 ao longo do comprimento, do gol da esquerda para o da direita como na câmera principal; `y` de 0 a 68 na largura, com `y = 0` na lateral do alto da imagem (a do lado de lá). Definido em `pitch.py`.
- **Normalizado (padrões, estatísticas por time, leitura tática, movimentação):** cada time aparece **atacando para a direita**, próprio gol em `x = 0`, e a **esquerda do time em `y` pequeno**. `patterns.normalize(points, defends_left)`: se o time defende o gol da direita, `(x, y) → (105 − x, 68 − y)`.
- **Na tela:** o campo 3D e o campinho animado desenham `y = 0` no alto. No painel, quem ataca vai sempre da esquerda para a direita; quem defende aparece girado (`mirror`), protegendo o gol da direita.

## Detecção (por frame)

`detector.py`. YOLO com `conf = 0.25` na resolução escolhida (960 por padrão). Com os modelos COCO, só `person` e `sports ball`; com o modelo de futebol, `player`, `goalkeeper`, `referee`, `ball`. Meia precisão na GPU.

## Tracking e papéis

`pipeline.py`.

1. **Corte de câmera** (`CutDetector`): histograma HSV 30 × 16 de uma miniatura 160 × 90; correlação com o frame anterior abaixo de 0,55 = corte. No corte: tracker novo (IDs continuam a contar a partir do maior), bola, homografia e IDs dos fantasmas zerados.
2. **BoT-SORT** (`make_tracker`): ajustado para `TRACK_FPS = 7`, jogador escondido volta com o mesmo ID por cerca de 2 s (`lost_track_buffer = 14`), limiares baixos de confiança (0,3 / 0,35), IoU tolerante e caixas expandidas (`BIoU(buffer_ratio=0.3)`), compensação do movimento da câmera (`enable_cmc`).
3. **Rótulo de cada ID**: `TrackLife` conta os rótulos que o detector deu ao ID; vale o mais frequente.
4. **Tomada aberta** (`is_wide_shot`): pelo menos 6 pessoas e altura mediana das caixas ≤ 18% da imagem. Só tomadas abertas calibram os times e disparam o OCR.
5. **Papel final**: quem é `pessoa`/`jogador` recebe o time pelo voto de cor; se a cor fica longe dos dois times vira `"árbitro/goleiro"`. `goleiro` e `árbitro` do modelo de futebol ficam como estão; o goleiro vai para o time cujos jogadores estão, em média, mais perto dele na horizontal da imagem.

## Times pela cor da camisa

`teams.py`.

- **Cor de um jogador** (`jersey_feature`): recorte do tronco (de 15% a 50% da altura da caixa, 25% de margem lateral), sem os pixels de gramado (HSV entre `[30,40,40]` e `[90,255,255]`), mediana em Lab com o brilho `L` multiplicado por `L_WEIGHT = 0.5` (sombra pesa menos que cor).
- **Calibração** (`TeamClassifier`): junta as cores das tomadas abertas. Quando há pelo menos 8 frames abertos e 80 cores (ou depois de 30 s com 40 cores), roda `fit_teams`: k-means com até 4 grupos, 3 sementes; os dois maiores grupos com distância ≥ 15 entre si viram os times; fica a semente que cobre mais pontos. **Time A (índice 0) é o de camisa mais clara.**
- **Classificação** (`TeamModel.classify`): time mais próximo, a não ser que a distância passe de `max(2,5 × espalhamento do time, 18) × tolerância`, quando vira `OUTLIER` (2). A tolerância é 1,8 para quem o modelo de futebol chamou de `jogador` (`PLAYER_LABEL_TOLERANCE`), 1,0 para `pessoa`.
- **Votos**: cada ID guarda os últimos 12 votos; vale a maioria (`team_of`).
- **Autocorreção**: com 200+ classificações recentes, se mais de 45% são `OUTLIER` ou um time tem menos de 12%, a calibração recomeça sozinha (`recalibrations` aumenta). A pessoa também pode mandar `recalibrate_teams`.

## Bola

`ball.py`. Entre várias candidatas, a mais perto da posição prevista (última posição + velocidade suavizada × tempo); sem previsão, a de maior confiança. Sem detecção por até 0,6 s, a posição é estimada e marcada `e: true`.

## Campo e homografia

`pitch.py`.

1. **Pontos-chave**: YOLOv8 pose com 32 pontos (cantos, áreas, pequenas áreas, marcas do pênalti, meio-campo, círculo). Valem os de confiança ≥ 0,5, fora de uma borda de 1% da imagem e com pelo menos 25% de gramado na vizinhança (`keypoints_on_grass`).
2. **Encaixe** (`fit_homography`): pelo menos 4 pontos que não estejam numa reta (espalhamento ≥ 8 m), RANSAC com limiar de 1,5 m, pelo menos 5 inliers e metade dos pontos concordando, erro de reprojeção médio ≤ 1,5% da largura (mínimo de referência 640 px). Cada recusa grava o motivo em `LAST_FIT["reason"]` (`poucos pontos`, `pontos alinhados`, `ransac falhou`, `poucos pontos concordantes`, `erro de reprojeção alto`, `fora do campo`).
3. **Orientação** (`orient`): se o mapa sairia espelhado, inverte a largura (`FLIP_Y`), para a lateral do alto da imagem ficar em `y = 0`.
4. **Plausibilidade** (`plausible`): o centro da metade de baixo da imagem tem que cair no campo (com 15 m de folga) e os cantos de controle a até 60 m dele.
5. **Suavização**: cinco pontos fixos da imagem são levados para o campo e suavizados entre frames (`SMOOTHING = 0.5`); a homografia final é refeita a partir deles.
6. **Sem encaixe por pouco tempo**: a última homografia vale por até 1,5 s, com `fresh = False` (o mapa se move, mas padrões e estatísticas não gravam esse frame).
7. **Close** (`is_close_up`): alguém com altura ≥ 25% da imagem; a homografia é zerada.
8. **Cena** (`scene` no mapa): `"ao vivo"`, `"close"`, `"sem campo"`, `"sem modelo do campo"`.
9. **Área visível** (`visible_area`): polígono, em metros, da parte do campo que a câmera mostra; usado para saber se a linha de defesa inteira está na imagem.

## Mapa em metros

`fieldmap.py`. Os pés (centro de baixo da caixa) de cada ID vão para metros e são suavizados (60% da posição nova). Quem sai da imagem vira **fantasma** na última posição por até 4 s (IDs com mais de 1 s de vida), e some se um ID novo aparecer a até 6 m. Quem está a mais de 1,5 m fora das linhas não entra (banco, gandulas). Goleiro a mais de 30 m do próprio gol vira jogador de linha; no máximo um goleiro por time.

## Quem ataca e de que lado cada time defende

`patterns.PatternStore`.

- **Lado** (`SideEstimator`): evidência acumulada com meia-vida de 120 s. Cada goleiro visto vale ±3 (perto do gol da esquerda ou da direita); o time mais recuado na média vale ±0,2. Com |placar| ≥ 1, decide se o time 0 defende a esquerda. Por isso os padrões continuam certos depois da troca de lado no intervalo.
- **Posse** (`_possession`): o jogador visível mais perto da bola, a até 4 m, por 2 frames seguidos, define o time com a bola; ela vale por até 3 s depois. Sem bola, ataca o time mais avançado em direção ao gol adversário, se a diferença for de pelo menos 6 m. Senão, o momento fica "sem fase". `phaseSource` conta quantos momentos foram decididos de cada jeito.
- **Momento válido**: só frames com homografia nova (`view.fresh`), com a partida gravando, e para cada time com pelo menos 5 jogadores de linha (fantasmas de até 2 s contam). O momento entra em `samples[(time, "ataque" | "defesa")]` já normalizado.

## Formação e posições médias

`patterns.compute_pattern`, a partir de pelo menos 40 momentos.

1. **10 posições médias**: k-means com k = 10 sobre todos os pontos (amostra de até 6000), 6 recomeços; fica o agrupamento com menor inércia × (1 + desequilíbrio de tamanhos). Cada posição guarda média, desvio (`sx`, `sy`) e fatia dos pontos.
2. **Linhas** (`split_lines`): as 10 posições, ordenadas pela profundidade, são cortadas nos tamanhos de cada formação conhecida (`FORMATIONS`: 4-4-2, 4-3-3, 4-2-3-1, 4-5-1, 3-5-2, 5-3-2, 4-1-4-1, 3-4-3, 5-4-1, 4-4-1-1, 4-3-2-1, 3-4-2-1, 3-4-1-2, 4-2-2-2, 4-1-3-2). Custo = variância de profundidade dentro das linhas / variância total + 0,12 × raridade da formação. Fica a de menor custo.
3. **Linha de defesa contada** (`back_line_members`): em cada frame em que a câmera mostra pelo menos 90% de uma faixa da largura do campo na altura da defesa, conta quem está a até 5 m do defensor mais recuado (entre 2 e 6 jogadores, ocupando pelo menos 22 m de largura). `back_line_summary`: com 30+ contagens e uma delas (entre 3 e 5) em 45%+ delas, ela vira a **estimativa**, e só formações com esse número atrás concorrem (`formationSource = "linha"`).
4. **Formação manual**: se a pessoa escolheu uma (`set_formation`), ela é usada direto (`formationSource = "manual"`). A escolha fica gravada na partida.
5. **Nomes** (`name_roles`): por linha, da esquerda para a direita. Defesa: 3 → ZAG ZAG ZAG; 4 → LE ZAG ZAG LD; 5 → LE ZAG ZAG ZAG LD. Ataque: 1 → CA; 2 → CA CA; 3 → PE CA PD. Meio: 1 → VOL; 2 → VOL VOL; 3 → MC MC MC (o mais recuado dos centrais vira VOL); 4 → ME/ALE MC MC MD/ALD; 5 → idem com 3 centrais. Segunda linha do meio nas formações de 4 linhas: MEI, MEI MEI, PE MEI PD, ME MEI MEI MD. Com três zagueiros, os abertos do meio são alas (ALE/ALD).
6. **Números**: `lineHeight` (média da linha de defesa), `block` (baixo < 30 m ≤ médio < 42 m ≤ alto), `width` (amplitude das posições médias), `depth` (ataque − defesa), `corridors` (no último terço, x > 70: esquerda y < 22,7, centro, direita y > 45,3), `heat` (grade de 5 m, normalizada).

## Defesa → ataque e "quem é quem"

`patterns.transition`. Cada posição da defesa é ligada a uma do ataque pelo casamento de menor custo (`scipy.optimize.linear_sum_assignment`), com custo = |Δy| + 0,35 × |Δx| + 8 × diferença relativa de linha. **No ataque, cada posição herda o nome que tem na defesa** (o lateral que sobe até o meio continua "LE"). `highlights` gera frases: quanto o time avança em média; lateral/ala que sobe 6+ m a mais que o time ou fica (4+ m a menos); ponta que fecha ou abre 6+ m; volante que fica a até 6 m da linha de defesa e a até 12 m do meio no ataque (ajuda na saída de bola).

## Movimentação (campinho animado)

`flows.team_flow`, a partir de 90 momentos (3 × 30).

1. Os momentos da fase são ordenados pela altura média do time e divididos em três partes iguais. Ataque: **saída de bola** (mais recuado) → **progressão** → **chegada**. Defesa: **pressão alta** (mais adiantado) → **bloco médio** → **bloco baixo**.
2. Cada etapa sorteia até 200 momentos. As 10 posições do padrão são reajustadas com os momentos da etapa por 4 iterações; **em cada momento, cada jogador visto vai para uma posição diferente** (casamento de menor custo, com custo máximo de 22 m para "ficar sem posição"), o que mantém a identidade de cada posição. Começa pela etapa do meio (partindo das posições médias deslocadas para a altura dela) e segue para as pontas, cada uma partindo da vizinha.
3. Posição com menos de 3,5% dos pontos da etapa (o normal é 10%) fica `estimated` (aparece apagada).
4. `flow_notes`: quem forma a última linha em cada etapa (até 6 m do mais recuado, ignorando posições estimadas), quem não é defensor e cai na linha (volante na saída, ponta no bloco baixo), quanto o time sobe ou recua, e até 4 posições que mais se destacam (sobem 8+ m a mais que o time, seguram, recuam 7+ m a mais, ficam adiantadas, abrem ou fecham 6+ m).
5. Recalculado a cada 200 momentos novos ou quando a formação/nomes mudam (`PatternStore._flow`, cache por time e fase).

## Passes e cruzamentos repetidos (setas)

- **Passe** (`PatternStore._track_pass`): com a posse decidida pela bola e a bola vista, o dono é o jogador do time com a bola mais perto dela, a até 2,5 m, com ID. Passe = o dono muda para outro ID do mesmo time em até 4 s e a bola andou 8+ m. Guardado normalizado `(horário, time, x0, y0, x1, y1)`.
- **Cruzamento** (`BallPlays`): a bola entra na área vinda da faixa lateral do último terço (x ≥ 70, até 18 m da lateral), andando 12+ m em até 1,8 s. Guardado em `cross_paths`.
- **Agrupamento** (`flows.ball_arrows`): o campo é dividido em 6 faixas de comprimento × 3 de largura; passes dentro da mesma zona são ignorados; os 3 pares de zonas mais repetidos com 3+ passes viram setas (da média das origens à média dos destinos). Cruzamentos: uma seta por lado com 2+ cruzamentos.

## Leitura tática

`tactics.py` + `patterns.team_tactics`.

- **Saída de bola**: com a bola no próprio terço (x ≤ 40, normalizado) e a defesa inteira na imagem, os jogadores da última linha são classificados: 2 → "2 zagueiros (laterais adiantados)"; 3 com um lado aberto (a menos de 14 m da lateral) → "3, com o lateral esquerdo/direito ficando"; 3 fechados com o do meio a até 8 m do centro → "3, com o volante entre os zagueiros"; 4 → "4 atrás"; 5+ → "5 atrás".
- **Jogadas com a bola** (`BallPlays`, só com a bola vista de fato): chute = bola a 18+ m/s indo para o gol a partir de x ≥ 60, pela faixa central (`10 ≤ y ≤ 58` e |vy| ≤ 0,7·vx), mirando até 5 m fora da trave → `chute_dentro` (da área) ou `chute_fora`; cruzamento como acima; entrada = bola entra na área sem ser cruzamento; condução pelo lado no último terço (x ≥ 62, faixa de 18 m) por 1,5+ s que se aproxima 7+ m do meio → `corta_dentro`, ou que avança 8+ m e segue aberta → `vai_fundo`. Cada tipo tem tempo de espera (3 a 5 s) para não contar o mesmo lance duas vezes.
- **Posições** (`role_texts`): laterais (sobe e apoia se x ≥ 55, até o meio se ≥ 42; por fora se a até 10 m da lateral, por dentro se 17+ m; passa por fora do ponta?), pontas (aberto até 8 m, por dentro 15+ m; corta para dentro ou vai ao fundo pelo lado dele), volantes (recua para a altura dos zagueiros; um segura e o outro chega), meias (entre as linhas, aberto, recuado, intermediária; meio-campo aberto se 35+ m entre os meias), centroavante (referência, recua, se movimenta).
- **Mudanças nos últimos 10 minutos** (`change_texts`): compara os últimos 600 s com o que veio antes: número de defensores, tipo de saída de bola, posição que mudou de faixa (7+ m) ou de altura (10+ m).

## Estatísticas da partida

`stats.StatsTracker.observe`, cada momento gravando.

- **Relógio** (`clock`): segundos desde o começo da partida, **sem as pausas** e parando ao finalizar.
- **Posse**: dono da bola = jogador visto a até 4 m dela por 2 frames; vale por 3 s. Ponderada pelo tempo de cada frame (`dt`, máximo de 0,5 s).
- **Domínio territorial** (`tilt`): de quem é o terço ofensivo onde a bola está (x ≥ 70 normalizado).
- **Passe**: o dono muda para outro jogador do mesmo time em até 5 s e a bola andou 3+ m. **Perda**: o dono muda para o outro time em até 5 s.
- **Pressão pós-perda**: nos 5 s depois da perda, média de jogadores do time que perdeu a até 5 m da bola; **recuperação em 5 s** se ele volta a ter a bola nesse tempo.
- **Forma do time** (`shape_of`, com 6+ jogadores): linha de defesa = média dos mais recuados (até 4), profundidade = do mais recuado ao mais avançado, largura = amplitude em `y`.
- **Corredor da bola** quando o time ataca: esquerda / centro / direita em terços da largura.
- **Distância**: soma dos deslocamentos de cada ID visto (no máximo 10 m/s, frames a até 0,6 s), em km. Fica bem abaixo da real.
- **Janelas**: `recentes` (últimos 300 s de jogo gravado) e `partida`; `timeline` por minuto (posse e linha de defesa).
- **Intervalo marcado** (evento `intervalo`, tecla I): enquanto ímpar, nada é gravado (`paused`).

## Alertas (regras)

`insights.evaluate_rules` e `tactic_alerts`, a cada atualização das estatísticas (3 s). Um alerta só se repete para a mesma regra e time depois de 6 min (mudanças táticas: 15 min). As regras dos últimos 5 minutos exigem 90+ s de jogo analisado na janela.

| Regra | Condição |
| --- | --- |
| `linha_alta` | linha de defesa ≥ 45 m nos últimos 3 minutos |
| `bloco_baixo` | linha de defesa ≤ 25 m nos últimos 3 minutos |
| `corredor` | 60%+ da bola no ataque pelo mesmo lado, com 60+ s de posse |
| `posse` | posse ≥ 65% com 90+ s de posse identificada |
| `territorio` | 70%+ do tempo com a bola no terço ofensivo |
| `perdas` | 6+ perdas e precisão de passe ≤ 65% |
| `pressao` | 4+ perdas e recuperação em 5 s em 50%+ delas |
| `espacado` | profundidade ≥ 48 m |
| `mudanca:*` | cada frase de "mudanças nos últimos 10 minutos" |
| `chuveirinho` | 5+ cruzamentos em 10 min e pelo menos o dobro das entradas |
| `chutes_fora` | 3+ chutes de fora em 10 min |

## Análise do LLM

`insights.InsightEngine`.

- **Quando**: o Ollama é conferido a cada 20 s. A primeira análise sai 1 min depois de o app subir; depois a cada `interval_s` (180, 240 ou 300 s, padrão 240), só se entrou 60+ s de jogo novo (senão tenta de novo em 30 s), nunca com a partida pausada/finalizada. **Analisar agora** força uma.
- **Entrada** (`build_summary`): minuto, placar, eventos, janelas recentes e da partida (com aviso quando há poucos dados), formações e como foram definidas, movimentos da defesa para o ataque, leitura tática de cada time e os últimos 6 alertas. Os nomes dos times entram no prompt.
- **Chamada**: `/api/chat` com `format` = esquema JSON, `think: false`, temperatura 0,3, contexto de 8192, `keep_alive: "1m"` (libera a memória da placa para a detecção logo depois), timeout de 240 s.
- **Saída** (`parse_analysis`): `leitura` (até 800 caracteres) e listas de até 3 itens (`funcionando`, `espacos`, `sugestoes`) e até 4 (`posicoes`). Vira um item `kind: "analise"` no feed.
- **Modelo**: padrão `qwen3:4b-instruct` (2,5 GB, divide a placa de 8 GB com a detecção); `qwen3:8b` como opção de texto melhor. O painel baixa o modelo pelo `/api/pull`.

## Dados oficiais e a análise combinada

`official.py` e `story.py`. Ao finalizar, a página manda `official_search`; o backend lê os jogos do dia na ESPN e pontua cada um pelas siglas do placar e pelas palavras do nome da partida (sem datas, números e palavras como "x", "cl", "liga"). A pessoa escolhe o jogo (`official_confirm`); o backend baixa o resumo, liga os times aos nossos pelas siglas (empate: casa = Time A) e grava em `match_meta.official`; **Trocar os times** inverte a ligação (`official_swap`).

Divisão do trabalho, quando há dados oficiais:

| Vem dos dados oficiais | Vem da análise do vídeo |
| --- | --- |
| placar, gols (minuto, autor, assistência), cartões | formação, posições médias, linhas, largura |
| posse, finalizações, no alvo, cruzamentos, passes, escanteios, faltas | laterais subindo, saída com 3, bloco baixo com 5, movimentação |
| | entradas na área, cortes para dentro, bola no campo de ataque, recuperação em 5 s |

Por quê: a posse medida bate com a oficial (a câmera vê a bola quase sempre), mas as contagens ficam abaixo do real porque a transmissão corta replays, closes e lances fora do quadro. No LLM, `build_summary` ganha `dados_oficiais` e o placar oficial, e o prompt manda usar os oficiais para números e o vídeo para a parte tática. Nos cards e no resumo final os textos são montados por regras (`story.py`), porque o modelo pequeno troca comparações e números.

## Nomes dos times pelo placar

`teamnames.py`. A cada 6 s (até confirmar; depois a cada 60 s), em tomada aberta, os 28% de cima da imagem passam pelo RapidOCR numa thread. Os textos viram linhas (juntando pedaços com sobreposição pequena); procura duas siglas de 2 a 4 letras maiúsculas com um separador (placar no meio: "MCI 0 3 PSG") ou uma embaixo da outra, ignorando siglas de emissoras e competições (`NOT_TEAMS`). O mesmo par lido 3 vezes é confirmado. Qual sigla é de qual time: pelas cores dos retângulos ao lado das siglas, comparadas com as cores das camisas (precisa de 15 de vantagem em Lab para trocar a ordem); sem cores, a ordem do placar. Os nomes ficam presos às cores (`anchors`), então continuam certos se a calibração recomeçar. Nomes digitados (`source = "manual"`) desligam o OCR.

## Cores mais fortes (campinhos e relatório)

`frontend/src/colors.ts` e `backend/app/report.py` (`vivid`), mesma regra: cores quase sem saturação viram quase branco (`#f5f7fa`, se claras), grafite (`#1f2329`, se escuras) ou cinza (`#9aa3ad`); as outras ficam com saturação ≥ 0,85 e luminosidade entre 0,42 e 0,55, mantendo o matiz.
