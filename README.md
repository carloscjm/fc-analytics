# FC Analytics

Analisador de futebol ao vivo que roda 100% no seu PC. Ele captura a aba do navegador com o jogo, detecta jogadores e bola, projeta tudo num mapa 3D visto de cima e gera estatísticas e insights em tempo real, sem nenhum serviço pago.

**Status:** Fase 1 (captura e detecção). A página captura a aba do jogo, envia frames ao backend e desenha as caixas de jogadores e bola sobre o vídeo, com fps e atraso medidos ao vivo.

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
| roboflow/sports | MIT |
| Datasets do Roboflow (jogadores, campo) | CC BY 4.0 (exige atribuição) |
| OpenCV 4.5+ | Apache 2.0 |
| scikit-learn | BSD-3-Clause |
| FastAPI | MIT |
| React, Vite, Three.js, react-three-fiber | MIT |
| Apache ECharts | Apache 2.0 |
| Ollama | MIT |
| Qwen3 (pesos) | Apache 2.0 |

Uso pessoal está liberado em todos. Se o projeto for distribuído ou virar produto usando Ultralytics YOLO, o código inteiro precisa ser publicado sob AGPL-3.0; a alternativa é trocar a detecção para RF-DETR.

Atribuição dos datasets: Roboflow, *football-players-detection* e *football-field-detection*, Roboflow Universe, CC BY 4.0.
