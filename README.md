# FC Analytics

Analisador de futebol ao vivo que roda 100% no seu PC. Ele captura a aba do navegador com o jogo, detecta jogadores e bola, projeta tudo num mapa 3D visto de cima e gera estatísticas e insights em tempo real, sem nenhum serviço pago.

**Status:** Fase 0 (ambiente). Backend e frontend sobem e conversam por WebSocket.

## Estrutura

```
backend/    Python + FastAPI: pipeline de análise (detecção, tracking, campo, estatísticas, insights)
frontend/   React + Vite + TypeScript: captura da aba, mapa 3D e painéis
instalar.bat  instala as dependências (Windows)
iniciar.bat   abre backend, frontend e o navegador (Windows)
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

1. Dê dois cliques em `instalar.bat` (só na primeira vez).
2. Dê dois cliques em `iniciar.bat`. O navegador abre em `http://localhost:5173`.
3. O cartão "Conexão com o backend" deve mostrar **conectado** e a latência em ms.

## Testes

Com o ambiente do backend ativo: `pytest` dentro de `backend/`.

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
