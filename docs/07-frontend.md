# 7. Frontend (painel)

Pasta `frontend/`. React 19 + TypeScript + Vite 7, Three.js (campo 3D) e Apache ECharts 6 (gráficos). Sem biblioteca de estado nem de componentes: tudo com `useState`/`useMemo` e CSS próprio em `styles.css`.

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `main.tsx` | monta o `<App />` |
| `App.tsx` | página inteira: conexão, estado, cabeçalho, as 8 opções de padrão, campo 3D, campinho de movimentação, painéis e coluna da direita |
| `backend.ts` | `BackendClient` (WebSocket com reconexão e ping) e **todos os tipos** das mensagens |
| `capture.ts` | `chooseTab` (`getDisplayMedia`), `FrameSender` (ticker num Web Worker, um frame em voo, recorte, JPEG), `packFrame` |
| `region.ts` | `VideoRegionFinder` + `RegionTracker`: acha a área do vídeo dentro da aba (a parte que muda entre frames) |
| `stats.ts` | `RollingStats`: fps e atraso de ponta a ponta (média e p95) |
| `pitch.ts` | medidas oficiais e `pitchLines()` (iguais às do backend), `projectToImage` |
| `DetectionOverlay.tsx` | canvas sobre o vídeo: caixas, IDs, bola e linhas do campo projetadas |
| `PatternField3D.tsx` | campo 3D (Three.js) com jogadores procedurais, rótulos das posições, anéis, setas, linhas da formação, mapa de calor |
| `FlowPitch.tsx` | campinho de movimentação em SVG, animado, com setas de passes/cruzamentos |
| `TacticsPanel.tsx` | leitura tática dos dois times |
| `MatchPanel.tsx` | placar, eventos (botões e atalhos), nomes dos times, estatísticas, gráficos, apagar dados |
| `InsightsPanel.tsx` | feed de alertas e análises, estado do LLM, baixar modelo, intervalo, coluna larga |
| `MatchControls.tsx` | botões da partida no cabeçalho e a janela **Criar partida** |
| `reportFile.ts` | escolher o arquivo do relatório (File System Access API), lembrar por partida (IndexedDB), gravar ou baixar |
| `colors.ts` | `vivid()`: cor da camisa mais forte para os campos |
| `EChart.tsx` | wrapper mínimo do ECharts |
| `styles.css` | todo o CSS, com tokens de cor e modo escuro (`prefers-color-scheme`) |

## Estado da página (`App.tsx`)

- **Conexão**: um `BackendClient` por aba; `onMessage` distribui as mensagens para `server` (status), `result` (último `detections`), `patterns`, `matchStats`, `insights`, `benchmark`, `notice`.
- **Captura**: `streamRef` (MediaStream da aba), `senderRef` (`FrameSender`), `capturing`. `startCapture` escolhe a aba e chama `startSending(stream)`, que manda `reset_session` e cria o `FrameSender`. Se o backend responder `stopCapture` (outra aba tomou a captura), `stopRef.current()` para tudo e mostra o aviso.
- **Cores**: `rawColors` = cores da calibração (`result.teams.colors`), senão as guardadas na partida (`matchStats.teamColors`), senão as padrão; `colors = vivid(...)` para todos os campos e painéis.
- **Nomes**: `matchStats.teamNames` (siglas do placar ou digitadas), senão "Time A"/"Time B".
- **Opções do campo** (`buildViews(names)`): 8 `View`s, cada uma com `parts` (`option` = chave em `patterns.options`, `team`, `mirror`, `ghost`), `attacker` e, nas de defesa → ataque, `transition`.

| Chave | Título | Partes |
| --- | --- | --- |
| `0-ataque` | A ataca | `0-ataque` |
| `0-defesa` | A defende | `0-defesa` (girado) |
| `1-ataque` | B ataca | `1-ataque` |
| `1-defesa` | B defende | `1-defesa` (girado) |
| `A-x-B` | A ataca × B defende | `0-ataque` + `1-defesa` (girado) |
| `B-x-A` | B ataca × A defende | `1-ataque` + `0-defesa` (girado) |
| `0-trans` | A: defesa → ataque | `0-defesa` (anéis, `ghost`) + `0-ataque`, setas de `patterns.transitions["0"]` |
| `1-trans` | B: defesa → ataque | idem para o time 1 |

Nas opções com dois times (`duo`), o campo 3D e o campinho não desenham as linhas da formação (`showLines={!duo}`).

- **Coluna larga dos insights**: lembrada no `localStorage` (`fca-insights-wide`).

## Captura (`capture.ts`, `region.ts`)

- `chooseTab()`: `getDisplayMedia` com vídeo de até 1920 × 1080 a 30 fps, sem áudio, escondendo a própria página da lista.
- `FrameSender`: um Web Worker faz o tique no intervalo escolhido (100–200 ms; continua no ritmo mesmo com a aba em segundo plano). A cada tique: pula se há frame em voo; pega o frame (`ImageCapture.grabFrame`, ou o `<video>`); atualiza o recorte; desenha num canvas de até 1280 × 720; JPEG com qualidade 0,75; manda. Frame sem resposta em 3 s conta como perdido.
- Recorte automático: compara miniaturas de 192 px de largura; pixels que mudam em pelo menos 2 comparações formam a área do vídeo; recortes menores que 12% da tela são descartados e os quase do tamanho da tela (≥ 95%) não recortam. O `RegionTracker` junta os recortes dos últimos 20 s para não pular.

## Campo 3D (`PatternField3D.tsx`)

- Cena Three.js com câmera de cima (`top`) ou 3D orbitável (`3d`). Gramado desenhado num canvas (listras, linhas, faixas atrás dos gols com a cor e o nome do dono, frase na lateral).
- Até 2 camadas (`PatternLayer`) de 10 jogadores procedurais (corpo, cabeça, chuteiras, camisa na cor do time) que deslizam até a posição média (`FOLLOW_RATE`). `mirror` gira a camada para defender o gol da direita.
- Rótulos (sprites) com o nome da posição, anéis no chão para a camada `ghost`, setas (`ArrowHelper`) para defesa → ataque, linhas da formação por setor (`SECTOR_COLORS`: defesa azul, meio amarelo, ataque vermelho), mapa de calor opcional.
- Recebe o padrão já normalizado; não conhece o lado real do campo.

## Campinho de movimentação (`FlowPitch.tsx`)

- SVG de 105 × 68 m. Para cada camada (`FlowLayer`: `flow`, `color`, `mirror`, `arrows`), as 10 peças são interpoladas entre as três etapas de `flow.stages`.
- Linha do tempo de uma volta (`CYCLE` ≈ 8,2 s): parado na etapa 1 (1,2 s), anda (2 s, easing cúbico), parado na etapa 2 (0,9 s), anda (2 s), parado na etapa 3 (1,6 s), some (0,5 s) e recomeça. A etapa da vez fica destacada embaixo (`flow-steps`). Com `prefers-reduced-motion`, troca de etapa a cada 2,5 s sem animação.
- Setas só para quem ataca (camada sem `mirror`): passes em branco, cruzamentos em amarelo, translúcidas, com a contagem (`3×`). Peças de posições `estimated` aparecem apagadas.
- Linhas da formação só quando há um time só.

## Partida e relatório

`MatchControls.tsx`, `reportFile.ts` e os callbacks em `App.tsx`.

| Estado (`matchStats.matchState`) | Botões |
| --- | --- |
| `livre` (ou sem estatísticas) | **Criar partida** |
| `ativa`, sem captura | **Escolher aba**, **Finalizar partida** |
| `ativa`, capturando | **Pausar captura**, **Finalizar partida** |
| `pausada` | **Retomar captura**, **Finalizar partida** |
| `finalizada` | **Criar partida**, **Salvar relatório de novo** |

- **Criar partida**: janela com nome (opcional) e "Escolher pasta e nome..." (`showSaveFilePicker`, Chrome/Edge). O arquivo escolhido fica em `pendingHandle` até chegar o `matchId` novo; aí é guardado no IndexedDB (`fca-analytics` → `reportFiles`, chave = `matchId`) e recuperado se a página recarregar.
- **Pausar**: pede a permissão de escrita do arquivo **antes de qualquer `await`** (precisa do gesto do clique), para o `FrameSender` mas mantém a aba compartilhada, manda `pause_match` e grava o relatório.
- **Retomar**: manda `resume_match`; se a aba ainda está compartilhada, `startSending(stream)` (com `reset_session`); senão, pede a aba de novo.
- **Finalizar**: dois cliques (confirmação de 4 s), permissão do arquivo, para a captura, `finish_match`, espera 800 ms e grava o relatório.
- **Gravar** (`writeReport`): `GET /report.html` e `createWritable()` no arquivo; sem arquivo ou sem permissão, baixa com `<a download>` (pasta Downloads).

## Outros painéis

- `MatchPanel`: placar e nomes (**⇄ Trocar**, **Editar**, **Ler do placar**), botões de evento e atalhos de teclado (G, C, V, S com Shift para o Time B; I intervalo; Z desfaz), tabela das janelas (**Últimos 5 min** / **Partida inteira**), gráficos ECharts de posse e linha de defesa por minuto com os eventos marcados, **Apagar dados** com confirmação.
- `TacticsPanel`: para cada time, mudanças nos últimos 10 minutos, posições, saída de bola, jogadas com a bola (tabela partida × últimos 10 min).
- `InsightsPanel`: estado do LLM (desligado, sem modelo com botão de baixar, baixando com progresso, pronto com contagem regressiva, analisando, erro), **Analisar agora**, intervalo, escolha do modelo, feed com alertas e análises, apagar um item ou tudo, expandir a coluna.
- Coluna da direita (em `App.tsx`): desempenho (fps, atrasos, tempos, frames enviados/pulados), último frame, times (calibração e **Recalibrar times**), tracking, conexão, modelo de futebol (baixar), medir modelos (benchmark).

## Convenções de UI

- Textos em português, frases curtas, sem jargão. Botões dizem a ação ("Pausar captura", "Salvar relatório de novo").
- Cores sempre por tokens CSS (`--bg`, `--card`, `--text`, `--muted`, `--border`, `--accent`, `--bad`...), com modo escuro.
- Time A e Time B: cor da camisa (`colors[t]`) e nome (`names[t]`), nunca "time 0/1" na tela.
- `localStorage` só para conveniências (coluna larga), sempre em `try/catch`.
