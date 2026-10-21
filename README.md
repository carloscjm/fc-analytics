# FC Analytics

Analisador de futebol ao vivo que roda 100% no seu PC. Ele captura a aba do navegador com o jogo, detecta jogadores e bola, projeta tudo num mapa 3D visto de cima e gera estatísticas e insights em tempo real, sem nenhum serviço pago.

**Status:** Fase 5 (insights e dicas). Além dos padrões de ataque e defesa e das estatísticas da partida, o app mostra alertas táticos na hora e, a cada 3 a 5 minutos, uma análise escrita por um LLM que roda no próprio PC (Ollama).

## Estrutura

```
backend/    Python + FastAPI: pipeline de análise (detecção, tracking, campo, estatísticas, insights)
frontend/   React + Vite + TypeScript: captura da aba, mapa 3D e painéis
instalar-ferramentas.bat  instala Python, Node.js, Git e Ollama pelo winget (Windows)
instalar.bat              instala as dependências do projeto (Windows)
iniciar.bat               abre backend, frontend e o navegador (Windows)
```

## Instalação no Windows (app)

1. Baixe o `FCAnalytics-win-Setup.exe` da página de [Releases](https://github.com/carloscjm/fc-analytics/releases/latest) e dê dois cliques.
2. Na primeira vez, o app pede a **pasta das partidas** (onde o banco com as partidas analisadas fica gravado) e clica em **Instalar**: ele baixa o Python 3.12, o PyTorch (com CUDA quando há placa NVIDIA) e as bibliotecas da análise, com o [uv](https://github.com/astral-sh/uv). Se encontrar a instalação antiga em `E:\fc-analytics`, traz os modelos e as partidas de lá.
3. Depois disso, abrir o app sobe a análise sozinho e abre o painel no Chrome. Os botões **Iniciar**, **Parar**, **Abrir painel**, **Buscar atualizações** e **Alterar...** (pasta das partidas) ficam na janela do app.
4. **Buscar atualizações** baixa a versão nova dos Releases, instala as bibliotecas novas (se a lista mudou) e reabre o app.

Onde fica cada coisa: o programa em `%LocalAppData%\FCAnalytics` (trocado a cada atualização); o ambiente Python, os modelos baixados, as configurações e o registro em `%LocalAppData%\FCAnalytics\runtime`; as partidas na pasta escolhida.

Para publicar uma versão nova: mude o número no arquivo `VERSION` (por exemplo `0.6.1`) e envie para a `main` (uma tag `v0.6.1` também funciona). A automação `.github/workflows/release.yml` (Windows, no GitHub) monta a página, o app de controle (.NET 8 + [Velopack](https://github.com/velopack/velopack), MIT) e o instalador, e publica nos Releases.

## Desenvolvimento (sem o app)

## Pré-requisitos (Windows)

| Item | Versão | Para quê |
| --- | --- | --- |
| Driver NVIDIA | recente (Game Ready ou Studio) | GPU para a detecção; o PyTorch já traz o CUDA, não precisa do CUDA Toolkit |
| Python | 3.12 | backend |
| Node.js | 22 LTS ou mais novo | frontend |
| Git | qualquer recente | versionamento |
| Ollama | mais recente | LLM local para os insights (Fase 5) |

Hardware de referência: RTX 4060 8 GB (cenário A do planejamento).

## Como rodar

1. Na primeira vez, dê dois cliques em `instalar-ferramentas.bat` e depois em `instalar.bat`.
   Se você já tinha rodado o `instalar.bat` na Fase 0, rode de novo: agora ele instala o PyTorch com CUDA e o YOLO.
2. Dê dois cliques em `iniciar.bat`. O navegador abre em `http://localhost:5173`.
3. Abra o jogo (ou o trecho no YouTube) em outra aba e clique em **Escolher aba**.
4. Para ver as caixas enquanto assiste, deixe a página do FC Analytics numa janela separada, ao lado do jogo.

## Como a Fase 1 funciona

- A página captura a aba com `getDisplayMedia` e, a cada 100 a 200 ms (você escolhe), reduz o frame para até 1280×720 e envia como JPEG.
- Cada pacote leva um cabeçalho de 12 bytes (id do frame e momento da captura) e depois o JPEG. O formato está em `backend/app/protocol.py`.
- Só um frame fica em processamento por vez. Se o anterior ainda não voltou, o próximo é pulado, para o atraso não crescer.
- O temporizador roda num Web Worker, então continua no ritmo certo mesmo com a página em segundo plano.
- O backend roda o YOLO26 na GPU (meia precisão) e devolve as caixas. O painel mostra fps de análise, atraso médio e p95, tempo de inferência e frames pulados.

## Como a Fase 2 funciona

- **Tracking:** o BoT-SORT (biblioteca `trackers`, da Roboflow) mantém um ID por jogador. Ele é o ByteTrack com compensação do movimento da câmera, o que ajuda quando a transmissão acompanha a jogada. Um jogador escondido por até cerca de 2 s volta com o mesmo ID.
- **Times:** para cada ID, o backend pega a cor do tronco sem o verde do gramado. Nos primeiros 30 s de jogo (ou antes, se já houver 14 jogadores vistos), agrupa as cores em dois times com k-means. Cada ID vota a cada frame, e vale a maioria.
- **Árbitro e goleiros:** com o YOLO26 oficial, quem fica longe das duas cores aparece como "árbitro/goleiro"; a separação entre os dois depende da posição no campo e entra na Fase 3. Com o modelo de futebol opcional, goleiro e árbitro vêm separados da própria detecção, e cada goleiro é atribuído ao time mais próximo dele na imagem.
- **Bola:** entre várias candidatas, fica a mais próxima de onde a bola deveria estar. Se ela some por até 0,6 s, a posição é estimada pela última velocidade e aparece tracejada como "bola?".
- **Na página:** caixas na cor real de cada time com o ID, painel de calibração dos times (com botão "Recalibrar times") e métricas de estabilidade dos IDs.

## Como a Fase 3 funciona

- **Pontos do campo:** o modelo `football-pitch-detection.pt` (YOLOv8 pose do [roboflow/sports](https://github.com/roboflow/sports), AGPL-3.0) acha até 32 pontos do campo: cantos, áreas, meio-campo, círculo central e marcas do pênalti. Ele é baixado sozinho na primeira vez que o backend sobe (cerca de 140 MB), do mesmo Google Drive indicado no `setup.sh` daquele projeto.
- **Pixel para metros:** com 4 ou mais pontos confiáveis (e que não estejam todos numa reta), uma homografia com RANSAC leva o pé de cada jogador para metros num campo oficial de 105 × 68 m. A homografia é suavizada entre frames.
- **Closes, replays e cortes:** um corte de câmera é detectado pela mudança brusca de cores entre frames; nele o tracking recomeça, para não juntar jogadores de tomadas diferentes. Closes (alguém muito grande na tela) e frames sem pontos suficientes pausam o mapa, que fica na última posição conhecida.
- **Fora da imagem:** quem sai da imagem continua valendo, na última posição conhecida, por até 4 s; um ID novo que aparece perto assume essa posição.
- **Recorte automático:** a página acha sozinha onde está o vídeo dentro da aba (a área que muda entre frames) e analisa só ela.
- **Linhas do campo sobre o vídeo:** com a opção ligada, as linhas projetadas aparecem em rosa sobre o vídeo. Se elas coincidem com as linhas reais do gramado, as posições em metros estão certas.
- **Diagnóstico:** `localhost:8000/debug/state`, `/debug/snapshot.jpg` (último frame com caixas e linhas do campo) e `/debug/map.png` (mapa em 2D).

## Padrões dos times (como cada um ataca e defende)

O campo 3D não mostra o jogo ao vivo. Ele resume o comportamento de cada time em 6 opções: **Time A ataca**, **Time A defende**, **Time B ataca**, **Time B defende** e as duas combinadas, **A ataca × B defende** e **B ataca × A defende**. Nas combinadas, os dois padrões vêm dos mesmos momentos do jogo: o time que ataca vai para a direita e o que defende aparece girado, defendendo o gol da direita.

- **Quem ataca:** em cada momento, o time do jogador mais perto da bola (até 4 m) está atacando. Sem bola visível, vale o time mais avançado em direção ao gol adversário. A posse vale por até 3 s depois da última vez que a bola foi vista.
- **Lado de cada time:** vem da posição dos goleiros (peso maior) e de onde cada time fica, com memória de cerca de 2 minutos; por isso os padrões continuam corretos depois da troca de lado no intervalo.
- **Normalização:** as posições são giradas para cada time aparecer sempre atacando da esquerda para a direita. Esquerda e direita são do ponto de vista do time.
- **Linha de defesa contada:** em cada quadro em que a câmera mostra o campo de lado a lado na altura da defesa, o app conta quantos jogadores (sem o goleiro) estão a até 7 m do defensor mais recuado. Com pelo menos 30 contagens e uma delas em 45% ou mais dos lances, esse número (3, 4 ou 5) define quantos zagueiros a formação tem. O painel mostra a contagem, por exemplo "3 atrás em 72% de 140 lances".
- **Corrigir a formação:** cada formação no painel tem um seletor; escolhendo uma (por exemplo 3-4-3), as posições, os nomes e as setas de defesa → ataque são refeitos com ela. A escolha fica salva com a partida e continua depois de "Zerar padrões"; **Automática** volta ao normal.
- **Formação:** as posições de cada time em cada fase são agrupadas em 10 posições médias (k-means com vários recomeços). Elas são separadas em linhas pela profundidade e comparadas com as formações que existem (4-4-2, 4-3-3, 4-2-3-1, 3-5-2, 5-3-2 e outras); fica a que encaixa melhor, com preferência pelas mais comuns quando as posições estão confusas.
- **Números:** altura média da linha de defesa (bloco baixo abaixo de 30 m do próprio gol, médio até 42 m, alto acima), largura, profundidade da defesa ao ataque, corredor preferido no último terço e mapa de calor.
- **Quando aparece:** cada opção precisa de pelo menos 40 momentos daquela fase em tomada aberta com o campo identificado. Os padrões são recalculados a cada 10 s, continuam acumulando mesmo se a captura recomeçar e só zeram no botão "Zerar padrões".
- **Limite:** a câmera da TV não mostra o campo inteiro, então as médias usam quem aparece na imagem (e quem saiu há até 2 s). É uma aproximação que melhora com mais minutos de jogo.
- **Diagnóstico:** `localhost:8000/debug/patterns`.

## Movimentação (campinho abaixo do campo principal)

Um segundo campo, só de leitura, mostra **como o time se movimenta** na opção escolhida em cima:

- **Ataque:** os momentos em que o time tem a bola são divididos em três etapas pela altura do time no campo: **saída de bola** → **progressão** → **chegada**. Cada posição vira um caminho: anel no começo, ponto no meio e o jogador com o nome no fim. Dá para ver o lateral que sobe e fecha para o meio, o volante que cai entre os zagueiros na saída, o ponta que abre. Em amarelo, as jogadas com a bola da partida: cruzamentos por lado, entradas na área e chutes de fora.
- **Defesa:** **pressão alta** → **bloco médio** → **bloco baixo**: como a formação se recompõe, quem entra na última linha (linha de 5) e quem fica adiantado.
- **Duas opções juntas** (A ataca × B defende) mostram os dois times; **defesa → ataque** mostra como o time ataca.
- Embaixo, frases curtas: quantos ficam na última linha em cada etapa, quanto o time sobe ou recua e as posições que mais se destacam.
- Precisa de pelo menos 90 momentos da fase. Posições que a câmera quase não mostrou numa etapa aparecem apagadas e tracejadas.

## Quem é quem e nomes dos times

- **Nomes dos times:** o app lê o placar da transmissão com um leitor de texto local (RapidOCR, Apache 2.0, roda na CPU) e usa as siglas, como MCI e PSG, em toda a página, nos alertas e na análise do LLM. Ele procura duas siglas lado a lado (com o placar no meio) ou uma embaixo da outra, e só confirma depois de ler o mesmo par 3 vezes. A sigla fica presa à cor da camisa; se ficar na cor errada, use **⇄ Trocar** no placar do painel. **Editar** permite digitar os nomes (aí o placar não muda mais); **Ler do placar** volta ao automático.
- **Nome das posições:** cada jogador do campinho mostra a posição (LE, ZAG, LD, VOL, MC, ME, MD, MEI, PE, PD, CA; ALE e ALD com três zagueiros), deduzida da linha em que está e do lado do campo. No padrão de ataque, cada posição mantém o nome que tem na defesa: o lateral que sobe até o meio continua "LE". A opção **Posições** liga e desliga as etiquetas.
- **Defesa → ataque:** uma opção para cada time mostra onde cada posição fica defendendo (anéis) e para onde vai atacando (jogadores), com setas. Embaixo, frases sobre os movimentos mais claros (lateral que apoia ou fica, volante que recua para perto dos zagueiros, pontas que fecham para o meio) e uma tabela com quanto cada posição avança e em que linha fica no ataque.
- **Limite:** as posições são médias de quem ocupa cada região, não jogadores identificados. A câmera mostra só parte do campo e os IDs recomeçam a cada corte.

## Leitura tática

O painel **Leitura tática** mostra, para cada time:

- **Mudanças nos últimos 10 minutos:** compara os últimos 10 minutos com o que veio antes, por exemplo "passou a defender com 5 atrás (antes eram 4)", "na saída de bola, passou de 4 atrás para 3 com o volante entre os zagueiros" ou "LE: antes jogava por fora, agora por dentro".
- **Posições:** com quantos defende; se cada lateral sobe e apoia por fora ou por dentro, e se passa por fora do ponta; se os pontas jogam abertos ou por dentro e se a jogada do lado deles corta para dentro ou vai ao fundo; se o volante recua para a altura dos zagueiros; onde os meias jogam (entre as linhas, abertos, recuados); se o centroavante fica na referência ou recua.
- **Saída de bola:** com a bola no próprio terço e a defesa inteira na imagem, quem forma a última linha: 2 zagueiros, 3 com o volante entre os zagueiros, 3 com um lateral que fica, 4 atrás.
- **Bola no ataque:** pelo caminho da bola (só quando ela aparece de fato), cruzamentos para a área, entradas na área com a bola dominada, chutes de fora e de dentro da área, e conduções pelos lados que cortam para dentro ou vão ao fundo, na partida e nos últimos 10 minutos.

As mudanças, o chuveirinho (5 ou mais cruzamentos em 10 minutos, o dobro das entradas trabalhadas) e os chutes de fora (3 ou mais em 10 minutos) também viram alertas, e a análise do LLM ganhou a seção "Posições e jogadas". As contagens dependem de a bola aparecer na imagem e são aproximadas.

## Limpeza da análise

- **Campo:** pontos do campo achados fora do gramado (faixas pretas, placar, menus da página) são descartados antes do encaixe do campo.
- **Fora das linhas:** quem está a mais de 1,5 m fora do campo (banco, gandulas, técnico) não entra no mapa nem nos padrões.
- **Goleiro:** só vale perto do próprio gol (até 30 m) e um por time; os outros "goleiros" viram jogadores de linha.
- **Cores:** quem o modelo de futebol chama de jogador pode ter a cor mais diferente da do time (sombra, sol) antes de virar "árbitro/goleiro".

## Estatísticas da partida (Fase 4)

- **Gravação:** cada momento de jogo em tomada aberta vai para `backend/data/partidas.sqlite` (posições de todos os jogadores, bola, medidas do momento, passes, perdas e eventos). Se o backend reiniciar, a partida continua de onde parou. Depois de 4 horas sem jogo, começa uma partida nova sozinha; o botão **Nova partida** zera na hora (estatísticas, eventos e padrões).
- **Janelas:** **Últimos 5 min** e **Partida inteira**, recalculadas a cada 3 s.
- **Métricas:** posse de bola (time do jogador mais perto da bola, até 4 m), domínio territorial (tempo com a bola no terço ofensivo), passes aproximados e precisão (bola trocando entre jogadores do mesmo time), perdas de bola, pressão pós-perda (jogadores a até 5 m da bola nos 5 s seguintes e quantas vezes recupera), altura da linha de defesa, compactação, largura, corredor da bola no ataque e distância percorrida por quem aparece na imagem.
- **Gráficos (ECharts):** posse por minuto e altura da linha de defesa por minuto, com os eventos marcados.
- **Atalhos de teclado** (com a página do FC Analytics em foco):

  | Tecla | Time A | Com Shift: Time B |
  | --- | --- | --- |
  | G | gol | gol |
  | C | cartão amarelo | cartão amarelo |
  | V | cartão vermelho | cartão vermelho |
  | S | substituição | substituição |

  **I** marca o intervalo (a coleta pausa) e, apertado de novo, o começo do 2º tempo. **Z** desfaz o último evento. Os mesmos eventos têm botões no painel.
- **Limites:** o relógio é o do app (começa quando a partida começa no app, não o do jogo). Passes, pressão e distância dependem do que aparece na imagem e são aproximados; a distância fica bem abaixo da real.
- **Apagar dados:** o link **Apagar dados** no painel da partida mostra quanto espaço o banco ocupa e, depois de confirmar, apaga todas as partidas gravadas (posições, estatísticas, eventos, padrões, alertas e análises) e devolve o espaço ao disco. Os modelos baixados e as configurações continuam.
- **Diagnóstico:** `localhost:8000/debug/stats`.

## Insights e dicas (Fase 5)

- **Alertas (na hora):** regras simples sobre as estatísticas, recalculadas a cada 3 s. Exemplos: linha de defesa alta (45 m ou mais do próprio gol) ou bloco baixo (25 m ou menos) por 3 minutos, 60% ou mais dos ataques pelo mesmo lado, posse de 65% ou mais, 70% ou mais do tempo no terço ofensivo, muitas perdas de bola, boa pressão depois de perder e time espaçado (48 m ou mais entre defesa e ataque). Cada alerta só se repete para o mesmo time depois de 6 minutos. As regras dos últimos 5 minutos precisam de pelo menos 1,5 minuto de jogo analisado.
- **Análise do LLM (a cada 3, 4 ou 5 minutos):** um resumo em JSON (placar, eventos, estatísticas das duas janelas, formações e alertas recentes) vai para o Ollama. A resposta volta em JSON com a leitura do jogo, o que está funcionando, os espaços que dá para explorar e sugestões para cada time. A análise roda em segundo plano e não trava a detecção; ela só acontece se entrou pelo menos 1 minuto de jogo novo desde a anterior. O botão **Analisar agora** pede uma na hora.
- **Modelo:** o padrão é o `qwen3:4b-instruct` (2,5 GB), que divide bem os 8 GB da placa com a detecção. O `qwen3:8b` (5,2 GB) escreve melhor, mas disputa a memória da placa. Os dois são baixados pelo próprio painel; a escolha fica salva em `backend/data/llm.json`.
- **Ollama:** precisa estar aberto (ele fica na bandeja do Windows). Os modelos ficam em `E:\ollama\models` (variável `OLLAMA_MODELS`).
- **Gravação:** os insights ficam no SQLite com a partida e voltam se o backend reiniciar.
- **Diagnóstico:** `localhost:8000/debug/insights`.

## Modelo de futebol (opcional)

No painel, **Baixar modelo de futebol** baixa o `football-player-detection.pt` (YOLOv8x, cerca de 130 MB) do Google Drive indicado no `examples/soccer/setup.sh` do projeto [roboflow/sports](https://github.com/roboflow/sports). Ele detecta `player`, `goalkeeper`, `referee` e `ball`. É gratuito e segue a licença AGPL-3.0 da Ultralytics.

## Escolher o tamanho do modelo

No painel, clique em **Medir modelos** com a captura ligada. O backend mede o YOLO26 n, s, m, l e x nos frames reais do jogo e recomenda o maior que fica abaixo de 50 ms no p95. Esse limite deixa folga para o tracking e a detecção do campo das próximas fases. Na primeira medição, os modelos que faltam são baixados para `backend/models/` (cerca de 200 MB no total).

Os modelos oficiais são treinados no COCO e detectam "pessoa" e "bola". Um modelo treinado em futebol (classes jogador, goleiro, árbitro, bola) pode ser colocado como arquivo `.pt` em `backend/models/`; ele aparece sozinho na lista de modelos.

## Testes

Com o ambiente do backend ativo: `pytest` dentro de `backend/`. O teste `test_detector.py` roda o YOLO de verdade numa foto de exemplo (baixa o `yolo26n.pt` na primeira vez).

## Trechos para teste offline

Os trechos de transmissão ficam no YouTube e são usados direto numa aba do navegador, do mesmo jeito que um jogo ao vivo. Nenhum vídeo é baixado nem versionado.

## Licenças

Componentes e licenças conferidos em 20/10/2026:

| Componente | Licença |
| --- | --- |
| Ultralytics YOLO (código e modelos treinados) | AGPL-3.0, ou licença Enterprise paga |
| RF-DETR (pacote e modelos N/S/M/L) | Apache 2.0 (variantes XL/2XL: PML 1.0) |
| supervision | MIT |
| trackers (BoT-SORT/ByteTrack) | Apache 2.0 |
| gdown (download do modelo de futebol) | MIT |
| roboflow/sports | MIT |
| Datasets do Roboflow (jogadores, campo) | CC BY 4.0 (exige atribuição) |
| OpenCV 4.5+ | Apache 2.0 |
| scikit-learn | BSD-3-Clause |
| FastAPI | MIT |
| React, Vite, Three.js | MIT |
| Modelo de pontos do campo (roboflow/sports, YOLOv8 pose) | AGPL-3.0 |
| Apache ECharts | Apache 2.0 |
| SQLite | domínio público |
| RapidOCR (leitura do placar) | Apache 2.0 |
| ONNX Runtime | MIT |
| SciPy | BSD-3-Clause |
| Ollama | MIT |
| .NET 8 | MIT |
| Velopack | MIT |
| uv | MIT ou Apache 2.0 |
| Qwen3 (pesos) | Apache 2.0 |

Uso pessoal está liberado em todos. Se o projeto for distribuído ou virar produto usando Ultralytics YOLO, o código inteiro precisa ser publicado sob AGPL-3.0; a alternativa é trocar a detecção para RF-DETR.

Atribuição dos datasets: Roboflow, *football-players-detection* e *football-field-detection*, Roboflow Universe, CC BY 4.0.
