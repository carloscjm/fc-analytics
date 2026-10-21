# FC Analytics

Analisador de futebol ao vivo que roda 100% no seu PC. Ele captura a aba do navegador com o jogo, detecta jogadores e bola, projeta tudo num mapa 3D visto de cima e gera estatísticas e insights em tempo real, sem nenhum serviço pago.

**Status:** Fase 3 (campo e padrões dos times). O app identifica o campo na imagem, converte as posições para metros e mostra, num campo 3D, como cada time ataca e como defende: formação, posições médias, linha de defesa, largura, profundidade, corredor preferido e mapa de calor.

## Estrutura

```
backend/    Python + FastAPI: pipeline de análise (detecção, tracking, campo, estatísticas, insights)
frontend/   React + Vite + TypeScript: captura da aba, mapa 3D e painéis
instalar-ferramentas.bat  instala Python, Node.js, Git e Ollama pelo winget (Windows)
instalar.bat              instala as dependências do projeto (Windows)
iniciar.bat               abre backend, frontend e o navegador (Windows)
```

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

O campo 3D não mostra o jogo ao vivo. Ele resume o comportamento de cada time em 4 opções: **Time A ataca**, **Time A defende**, **Time B ataca** e **Time B defende**.

- **Quem ataca:** em cada momento, o time do jogador mais perto da bola (até 4 m) está atacando. Sem bola visível, vale o time mais avançado em direção ao gol adversário. A posse vale por até 3 s depois da última vez que a bola foi vista.
- **Lado de cada time:** vem da posição dos goleiros (peso maior) e de onde cada time fica, com memória de cerca de 2 minutos; por isso os padrões continuam corretos depois da troca de lado no intervalo.
- **Normalização:** as posições são giradas para cada time aparecer sempre atacando da esquerda para a direita. Esquerda e direita são do ponto de vista do time.
- **Formação:** as posições de cada time em cada fase são agrupadas em 10 posições médias (k-means com vários recomeços). Elas são separadas em linhas pela profundidade, o que dá a formação (por exemplo, 4-4-2).
- **Números:** altura média da linha de defesa (bloco baixo abaixo de 30 m do próprio gol, médio até 42 m, alto acima), largura, profundidade da defesa ao ataque, corredor preferido no último terço e mapa de calor.
- **Quando aparece:** cada opção precisa de pelo menos 40 momentos daquela fase em tomada aberta com o campo identificado. Os padrões são recalculados a cada 10 s, continuam acumulando mesmo se a captura recomeçar e só zeram no botão "Zerar padrões".
- **Limite:** a câmera da TV não mostra o campo inteiro, então as médias usam quem aparece na imagem (e quem saiu há até 2 s). É uma aproximação que melhora com mais minutos de jogo.
- **Diagnóstico:** `localhost:8000/debug/patterns`.

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
| Ollama | MIT |
| Qwen3 (pesos) | Apache 2.0 |

Uso pessoal está liberado em todos. Se o projeto for distribuído ou virar produto usando Ultralytics YOLO, o código inteiro precisa ser publicado sob AGPL-3.0; a alternativa é trocar a detecção para RF-DETR.

Atribuição dos datasets: Roboflow, *football-players-detection* e *football-field-detection*, Roboflow Universe, CC BY 4.0.
