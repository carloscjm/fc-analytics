# 1. Visão geral

## O produto

O FC Analytics assiste a um jogo de futebol numa aba do navegador (transmissão ao vivo ou vídeo no YouTube) e mostra, em tempo real e no próprio PC:

- **Padrões de cada time** num campo 3D visto de cima: posições médias de cada time atacando e defendendo, formação, altura da linha de defesa, largura, profundidade, corredor preferido e mapa de calor. São 8 opções: cada time atacando, cada time defendendo, os dois cruzamentos "A ataca × B defende" e "B ataca × A defende", e "defesa → ataque" de cada time.
- **Movimentação**: um segundo campo, animado, em que as peças andam pelas três etapas da fase (saída de bola → progressão → chegada no ataque; pressão alta → bloco médio → bloco baixo na defesa), com setas só para os passes e cruzamentos que mais se repetiram.
- **Leitura tática** em texto: o que cada posição faz (lateral apoia por fora ou por dentro, volante cai entre os zagueiros etc.), saída de bola, jogadas com a bola (cruzamentos, entradas na área, chutes de fora, conduções) e mudanças nos últimos 10 minutos.
- **Estatísticas da partida**: posse, domínio territorial, passes, perdas, pressão pós-perda, linha de defesa, largura, compactação, corredores, distância percorrida, com janelas "últimos 5 min" e "partida inteira" e gráficos por minuto.
- **Insights**: alertas por regra na hora e uma análise escrita por um LLM local a cada 3 a 5 minutos.
- **Partida e relatório**: criar partida, pausar e retomar a captura, finalizar, e um relatório HTML completo salvo no arquivo que a pessoa escolher.

Quem usa é uma pessoa interessada em tática (torcedor, analista amador), num Windows com placa NVIDIA. O hardware de referência é uma **RTX 4060 de 8 GB**.

## Princípios

1. **100% gratuito e local.** Sem APIs pagas. Modelos abertos baixados uma vez. O LLM roda no Ollama.
2. **Tempo real sem travar.** O laço dos frames só faz o que precisa ser feito por frame; o resto roda em segundo plano com cadência própria.
3. **Honestidade sobre a precisão.** A câmera da TV mostra só parte do campo, então quase tudo é aproximado. Os textos da interface dizem isso e marcam o que tem poucos dados.
4. **Interface em português simples**, sem jargão técnico, para quem não programa.
5. **Fácil de instalar e atualizar**: um instalador para Windows e um botão de buscar atualizações.

## Fases do projeto

O projeto foi construído em fases, registradas num documento de planejamento fora do repositório. Os nomes aparecem em comentários do código.

| Fase | Entrega | Onde está |
| --- | --- | --- |
| 0 | Ambiente, scripts de instalação, checagem do PC | `instalar*.bat`, `backend/check_env.py` |
| 1 | Captura da aba, envio de frames, detecção YOLO, medição de desempenho | `frontend/src/capture.ts`, `backend/app/protocol.py`, `detector.py` |
| 2 | Tracking (BoT-SORT), times pela cor, bola | `pipeline.py`, `teams.py`, `ball.py` |
| 3 | Campo na imagem, homografia, mapa em metros, cortes e closes, recorte automático | `pitch.py`, `fieldmap.py`, `frontend/src/region.ts` |
| — | Padrões dos times (formação, posições, campo 3D) | `patterns.py`, `PatternField3D.tsx` |
| 4 | Estatísticas e gravação no SQLite, eventos manuais | `stats.py`, `MatchPanel.tsx` |
| 5 | Alertas e análise do LLM local | `insights.py`, `InsightsPanel.tsx` |
| 6 | Quem é quem (nomes das posições, defesa → ataque), nomes dos times pelo placar, limpeza da detecção, leitura tática | `patterns.py`, `teamnames.py`, `tactics.py`, `TacticsPanel.tsx` |
| — | App do Windows com instalador e atualizações | `launcher/`, `.github/workflows/release.yml` |
| — | Movimentação animada, passes e cruzamentos repetidos | `flows.py`, `FlowPitch.tsx` |
| — | Partida (criar, pausar, finalizar) e relatório | `stats.py`, `report.py`, `MatchControls.tsx`, `reportFile.ts` |

## Glossário de futebol usado no código

| Sigla / termo | Significado |
| --- | --- |
| `GOL` | goleiro (fica fora das 10 posições dos padrões) |
| `ZAG` | zagueiro |
| `LE` / `LD` | lateral esquerdo / direito |
| `ALE` / `ALD` | ala esquerdo / direito (com três zagueiros) |
| `VOL` | volante (o meio-campista mais recuado) |
| `MC` | meio-campista central |
| `ME` / `MD` | meia pela esquerda / direita |
| `MEI` | meia (mais avançado, armador) |
| `PE` / `PD` | ponta esquerda / direita |
| `CA` | centroavante |
| `ATA` | atacante (quando a linha de ataque tem mais de 3) |
| linha de defesa | a última linha de jogadores de linha; a "altura" é a distância média dela até o próprio gol |
| bloco baixo / médio / alto | linha de defesa abaixo de 30 m, entre 30 e 42 m, acima de 42 m do próprio gol |
| saída de bola | o time com a bola no próprio terço, começando a jogada |
| chuveirinho | muitos cruzamentos para a área |
| entrada (na área) | entrar na área com a bola dominada, sem cruzamento |
| corta para dentro / vai ao fundo | condução pelo lado que fecha para o meio ou segue pela linha de fundo |
| terço ofensivo | o último terço do campo (x > 70 m, com o time atacando para a direita) |
| corredor | faixa do campo: esquerda (y < 22,7 m), centro, direita (y > 45,3 m), do ponto de vista do time |
| tomada aberta | plano da câmera principal, com muitos jogadores pequenos na tela (o que a análise usa) |
| close / replay | planos fechados ou repetições, que pausam a coleta |
