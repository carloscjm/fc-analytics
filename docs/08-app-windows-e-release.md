# 8. App do Windows e release

## O app de controle (`launcher/`)

C# com .NET 8 e WPF, **sem XAML** (a interface é montada em código em `MainWindow.cs`). Atualizações com [Velopack](https://github.com/velopack/velopack) 1.2.158 lendo os Releases do GitHub. O app não analisa nada: instala o ambiente, sobe e derruba o backend, abre o painel e atualiza.

| Arquivo | Papel |
| --- | --- |
| `FCAnalytics.csproj` | `net8.0-windows`, `UseWPF`, `StartupObject = FCAnalytics.Program`, ícone `app.ico`, pacote `Velopack` |
| `Program.cs` | `VelopackApp.Build().Run()` **antes de tudo** (trata instalar/desinstalar/atualizar), depois abre a `MainWindow` |
| `Paths.cs` | onde fica cada coisa (abaixo) |
| `Settings.cs` | `runtime\settings.json`: `DataDir`, `TorchIndex`, `RequirementsHash`, `SetupDone` |
| `Shell.cs` | roda programas sem janela preta, repassando a saída para o registro |
| `Installer.cs` | instala o ambiente Python com o `uv` que vem junto |
| `Backend.cs` | sobe/derruba o uvicorn, confere `/health` e o Ollama, abre o painel |
| `MainWindow.cs` | interface: configuração inicial, painel de status, botões, registro |

> Atenção: no WPF as `using` de `System.IO`, `System.Linq` etc. **não** vêm implícitas. Todos os arquivos têm as `using` explícitas no topo; mantenha isso ao criar arquivos novos, senão o CI falha (já aconteceu com `StreamWriter`).

### Onde fica cada coisa (`Paths.cs`)

| Caminho | Conteúdo |
| --- | --- |
| pasta do programa (`AppContext.BaseDirectory`, dentro de `%LocalAppData%\FCAnalytics\current`) | o app, `app\backend` (código Python), `app\web` (página montada), `tools\uv.exe`. **Trocada a cada atualização.** |
| `%LocalAppData%\FCAnalytics\runtime\python` | Python 3.12 baixado pelo uv |
| `...\runtime\venv` | ambiente com PyTorch e as bibliotecas |
| `...\runtime\uv-cache` | cache do uv (limpo no fim da instalação) |
| `...\runtime\models` | modelos baixados |
| `...\runtime\logs\backend.log` | registro do backend (acrescentado a cada início) |
| `...\runtime\settings.json` | configurações do app |
| pasta das partidas (escolhida) | `partidas.sqlite`, `llm.json`; sugestão `E:\FC Analytics\partidas` se existir o disco E:, senão `Documentos\FC Analytics\partidas` |

### Primeira execução (instalação)

`MainWindow.InstallAsync` → `Installer.InstallAllAsync(torchIndex)`:

1. `uv python install 3.12` (com `UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PYTHON_PREFERENCE=only-managed`, `UV_LINK_MODE=copy`).
2. `uv venv runtime\venv --python 3.12`.
3. PyTorch: `nvidia-smi` dá o driver; driver ≥ 580 → índice `cu130`; outro driver NVIDIA → `cu126`; sem NVIDIA → CPU.
4. `uv pip install -r requirements.txt` e `uv pip install --no-deps rapidocr==3.9.2`.
5. `uv cache clean`.
6. Se achar uma instalação antiga (`E:\fc-analytics` ou `Documentos\fc-analytics`, do tempo dos `.bat`) e a caixa estiver marcada, copia `backend\models` e `backend\data` sem sobrescrever (`ImportOld`).
7. Grava `settings.json` (`SetupDone = true`, hash do `requirements.txt`) e sobe o backend.

### Execuções seguintes

`OnLoadedAsync`: confere a GPU, `EnsureRequirementsAsync` (se o hash do `requirements.txt` mudou depois de uma atualização, reinstala as bibliotecas), sobe o backend com o painel e checa atualizações em silêncio (só destaca o botão).

### Backend (`Backend.cs`)

- `Start(dataDir)`: `runtime\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, na pasta `app\backend`, sem janela, com `FCA_DATA_DIR`, `FCA_MODELS_DIR`, `FCA_WEB_DIR`, `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`; saída para o registro e para `backend.log`.
- Antes de subir: se já existe algo respondendo em `:8000/health` (por exemplo o `iniciar.bat` antigo), não sobe e avisa. Se o Ollama não responde em `:11434/api/version`, tenta abrir `%LocalAppData%\Programs\Ollama\ollama app.exe`.
- A cada 2 s (`RefreshStatusAsync`): status do backend e do Ollama; quando `/health` responde pela primeira vez, abre o painel no Chrome (`OpenPanel`, ou no navegador padrão).
- **Abrir/instalar o Ollama**: abre se instalado; senão oferece instalar com `winget install --id Ollama.Ollama`.
- **Alterar...** a pasta das partidas: para o backend, move os arquivos (se a pessoa quiser), grava e sobe de novo.
- Ao fechar a janela, o backend para (`Kill(entireProcessTree)`).

### Atualizações

`UpdateManager(new GithubSource("https://github.com/carloscjm/fc-analytics", null, false))`. **Buscar atualizações**: `CheckForUpdatesAsync` → pergunta → `DownloadUpdatesAsync` (usa o pacote delta quando há) → para o backend → `ApplyUpdatesAndRestart`. Só funciona na versão instalada pelo Setup (`IsInstalled`).

A checagem usa a API do GitHub **sem autenticação**, limitada a 60 pedidos por hora por IP. Se você (agente) consultar muito a API do GitHub a partir da rede da pessoa, o botão pode falhar por até uma hora.

## Pipeline de release (`.github/workflows/release.yml`)

Dispara com push na `main` que muda `VERSION`, com tag `v*` ou manualmente (`workflow_dispatch`). Roda em `windows-latest`:

1. Versão: da tag (`v0.8.1` → `0.8.1`) ou do arquivo `VERSION`.
2. `npm ci && npm run build` em `frontend/`.
3. `dotnet publish launcher/FCAnalytics.csproj -c Release -r win-x64 --self-contained -o publish -p:Version=<versão>`.
4. Copia `backend/app` (sem `__pycache__`), `requirements.txt` e `check_env.py` para `publish/app/backend`, `frontend/dist` para `publish/app/web`, e baixa o `uv.exe` (versão fixada em `UV_VERSION`) para `publish/tools`.
5. `vpk download github` (versão anterior, para gerar o delta; pode falhar na primeira vez).
6. `vpk pack -u FCAnalytics -v <versão> -p publish -e FCAnalytics.exe --packTitle "FC Analytics" --packAuthors "Carlos" -i launcher/app.ico`.
7. `vpk upload github --publish --releaseName "FC Analytics <versão>" --tag v<versão>`.

Arquivos publicados no Release: `FCAnalytics-win-Setup.exe` (instalador, ~95 MB), `FCAnalytics-win-Portable.zip`, `FCAnalytics-<versão>-full.nupkg`, `FCAnalytics-<versão>-delta.nupkg`, `RELEASES`, `releases.win.json`. Leva cerca de 13 minutos.

### Como publicar uma versão

1. Termine e teste a mudança.
2. Mude o arquivo `VERSION` (por exemplo `0.8.1` → `0.8.2`) **e** a constante `VERSION` em `backend/app/main.py`.
3. Commit e push na `main`. Acompanhe com `gh run list -R carloscjm/fc-analytics` e confira os arquivos com `gh api repos/carloscjm/fc-analytics/releases/tags/v0.8.2`.
4. Na máquina da pessoa: **Buscar atualizações** no app. Depois de atualizar, a aba antiga do painel deve ser fechada (senão duas abas disputam a captura; o backend aceita só a última que começou a capturar).

Não mude `VERSION` em commits que não devem gerar instalador (documentação, ajustes internos sem efeito para quem usa). Se um push de tag falhar no seu ambiente, use a mudança do `VERSION` (é o caminho principal).

O instalador não tem assinatura digital (certificado pago): o Windows mostra "O Windows protegeu o computador" na primeira instalação (**Mais informações → Executar assim mesmo**).

## Fluxo antigo com `.bat` (desenvolvimento no Windows)

- `instalar-ferramentas.bat`: instala Python 3.12, Node.js LTS, Git e Ollama pelo `winget`.
- `instalar.bat`: cria `backend\.venv`, instala o PyTorch (CUDA pelo driver, como no app), `requirements-dev.txt` (com o pytest), `rapidocr --no-deps`, o `npm install` do frontend e roda o `check_env.py`.
- `iniciar.bat`: abre duas janelas (backend com `--reload` em `:8000`, frontend Vite em `:5173`) e o navegador. Atualiza as bibliotecas no início.

Os `.bat` usam fim de linha CRLF (`.gitattributes`). Não use os dois fluxos ao mesmo tempo: ambos usam a porta 8000.
