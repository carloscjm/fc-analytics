# AGENTS.md — guia para agentes de IA

Este arquivo é a porta de entrada para qualquer agente (Claude, Codex, Copilot, Cursor etc.) que for trabalhar no FC Analytics. Leia inteiro antes de mexer no código. A documentação detalhada fica em [`docs/`](docs/README.md).

## O que é o projeto

O FC Analytics é um analisador de futebol que roda 100% no PC de quem usa, sem nenhum serviço pago. A página (React) captura a aba do navegador com o jogo e manda frames JPEG por WebSocket para um backend Python (FastAPI). O backend:

1. detecta jogadores, goleiros, árbitro e bola com YOLO;
2. segue cada jogador com um ID (BoT-SORT) e separa os dois times pela cor da camisa;
3. acha o campo na imagem (pontos-chave + homografia) e converte cada jogador para metros num campo de 105 × 68 m;
4. acumula os padrões de cada time atacando e defendendo (formação, posições, movimentação, passes e cruzamentos repetidos, leitura tática);
5. grava a partida no SQLite e calcula estatísticas (posse, passes, perdas, pressão, linha de defesa...);
6. gera alertas por regra e, a cada 3 a 5 minutos, uma análise escrita por um LLM local (Ollama + Qwen3);
7. exporta um relatório HTML da partida.

Há também um app de controle para Windows (.NET 8 + WPF + Velopack) que instala o ambiente Python, sobe o backend, abre o painel e busca atualizações nos Releases do GitHub.

## Mapa rápido do repositório

```
AGENTS.md                 este arquivo
CLAUDE.md                 aponta para este arquivo (lido pelo Claude Code)
README.md                 manual de uso, para quem usa o app
VERSION                   versão do app; mudar este arquivo na main publica um Release
docs/                     documentação técnica completa (comece por docs/README.md)
backend/app/              backend Python (FastAPI): detecção, tracking, campo, padrões, estatísticas, insights, relatório
backend/tests/            testes pytest
frontend/src/             página React + TypeScript + Vite (captura, campo 3D, painéis)
launcher/                 app de controle do Windows (C#, .NET 8, WPF sem XAML, Velopack)
.github/workflows/        release.yml: monta o instalador e publica nos Releases
iniciar.bat, instalar.bat, instalar-ferramentas.bat   fluxo antigo de desenvolvimento no Windows
```

## Regras de ouro

1. **Tudo gratuito e local.** Nenhuma API paga, nenhum serviço em nuvem obrigatório. O LLM roda no Ollama da própria máquina. Antes de adicionar uma dependência, confira a licença e registre na tabela de licenças do `README.md`.
2. **Português do Brasil** em tudo que a pessoa vê (textos da página, do app, do relatório, mensagens de erro, alertas, prompts do LLM) e nos comentários e docstrings do código. Nomes de variáveis e funções ficam em inglês ou português, seguindo o arquivo em que você está. Escreva frases curtas, concretas e sem jargão para quem não é programador: quem usa é um torcedor/analista, não um engenheiro.
3. **Convenção de coordenadas.** Campo em metros, `x` de 0 a 105 (comprimento) e `y` de 0 a 68 (largura, `y = 0` é a lateral do alto da imagem). Nos padrões, cada time é **normalizado** para atacar da esquerda para a direita (próprio gol em `x = 0`) e a esquerda do time fica em `y` pequeno. Veja `docs/04-algoritmos.md`.
4. **Time 0 = Time A, time 1 = Time B.** O Time A é o de camisa mais clara na calibração. Os nomes reais (siglas do placar) ficam presos à cor da camisa, não ao índice.
5. **Não trave o laço dos frames.** A detecção roda a cerca de 3 a 7 frames por segundo. Cálculos pesados (resumo dos padrões, estatísticas, LLM, OCR) rodam em threads de fundo com cadência própria (10 s, 3 s, 3–5 min, 6 s). Se você criar algo pesado, siga o mesmo modelo (`_maybe_summarize`, `_maybe_stats` em `pipeline.py`).
6. **Uma aba captura por vez.** O backend só aceita frames da conexão que mandou `reset_session` por último (`app.state.capturer`). Não remova isso: frames de duas abas misturados zeram o tracking a cada frame.
7. **Testes antes de publicar.** Rode `pytest` em `backend/` (veja abaixo) e `npm run build` em `frontend/` (o build roda o `tsc`). Adicione testes para lógica nova no backend.
8. **Publicar = mudar o `VERSION`.** Cada push na `main` que muda o arquivo `VERSION` dispara o `release.yml`, que monta o instalador e publica nos Releases; o app do usuário encontra a versão nova pelo botão **Buscar atualizações**. Mantenha `VERSION` e a constante `VERSION` de `backend/app/main.py` iguais. Não mude o `VERSION` em commits que não devem virar release (por exemplo, só documentação).
9. **Nada de dados ou modelos no git.** `*.pt`, `*.onnx`, `*.sqlite`, `models/`, `data/` estão no `.gitignore`. Os modelos são baixados na primeira vez; as partidas ficam na pasta escolhida pela pessoa.
10. **Mudou comportamento visível? Atualize o `README.md`** (manual de uso) e o doc técnico correspondente em `docs/`.

## Comandos

```bash
# Backend (Python 3.12)
cd backend
python -m venv .venv && source .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install torch torchvision                             # com CUDA: --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements-dev.txt
pip install --no-deps rapidocr==3.9.2                     # sem dependências: ele traria um segundo OpenCV
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pytest                                                    # test_detector.py baixa o yolo26n.pt; test_ws.py precisa das bibliotecas completas

# Frontend (Node 22+)
cd frontend
npm install
npm run dev        # http://localhost:5173, com proxy para o backend em 8000 (vite.config.ts)
npm run build      # tsc -b + vite build -> frontend/dist (o backend serve essa pasta em http://localhost:8000/)

# App do Windows (só no Windows, ou no CI)
dotnet publish launcher/FCAnalytics.csproj -c Release -r win-x64 --self-contained -o publish
```

Para rodar só os testes rápidos (sem YOLO nem WebSocket): `pytest --ignore=tests/test_detector.py --ignore=tests/test_ws.py`.

## Diagnóstico com o backend rodando

| Endereço | O que mostra |
| --- | --- |
| `http://localhost:8000/health` | `{"status": "ok", "version": ...}` |
| `/debug/state` | último frame: fps, tempos, times, tracking, cena, encaixe do campo |
| `/debug/snapshot.jpg` | último frame com as caixas e as linhas do campo projetadas |
| `/debug/map.png` | mapa 2D visto de cima |
| `/debug/patterns` | resumo dos padrões (momentos, formação, linha) |
| `/debug/stats` | estatísticas da partida atual (JSON completo) |
| `/debug/insights` | feed de alertas/análises e estado do LLM |
| `/debug/names` | nomes dos times lidos do placar |
| `/report.html` | relatório da partida atual |

No app do Windows, o registro do backend fica em `%LocalAppData%\FCAnalytics\runtime\logs\backend.log`.

## Onde ler mais

| Documento | Assunto |
| --- | --- |
| [docs/01-visao-geral.md](docs/01-visao-geral.md) | produto, fases, princípios, glossário de futebol |
| [docs/02-arquitetura.md](docs/02-arquitetura.md) | componentes, fluxo de um frame, threads e cadências |
| [docs/03-backend.md](docs/03-backend.md) | cada módulo Python, classes, constantes, variáveis de ambiente |
| [docs/04-algoritmos.md](docs/04-algoritmos.md) | como cada análise funciona (times, campo, fases, formação, movimentação, estatísticas, alertas, LLM) |
| [docs/05-protocolo.md](docs/05-protocolo.md) | formato dos frames, todas as mensagens do WebSocket, endpoints HTTP |
| [docs/06-dados.md](docs/06-dados.md) | SQLite, metadados da partida, arquivos em disco, ciclo da partida |
| [docs/07-frontend.md](docs/07-frontend.md) | componentes React, estado, captura, campos 3D e animado, relatório |
| [docs/08-app-windows-e-release.md](docs/08-app-windows-e-release.md) | app de controle, instalação, atualizações, pipeline de release |
| [docs/09-desenvolvimento.md](docs/09-desenvolvimento.md) | ambiente, testes, previews, receitas para mudanças comuns |
| [docs/10-limitacoes-e-roadmap.md](docs/10-limitacoes-e-roadmap.md) | limites conhecidos, dívidas técnicas, ideias futuras |
