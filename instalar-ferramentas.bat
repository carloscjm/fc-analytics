@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === FC Analytics: instalacao das ferramentas no Windows ===
echo.
echo Este script instala, pelo winget (gerenciador oficial do Windows):
echo   - Python 3.12
echo   - Node.js LTS
echo   - Git
echo   - Ollama
echo Ao continuar, voce aceita as licencas desses programas.
echo O Windows pode pedir confirmacao de administrador para alguns deles.
echo.
pause

where winget >nul 2>nul
if not %errorlevel%==0 (
  echo O winget nao foi encontrado. Instale o "Instalador de Aplicativo" pela Microsoft Store e rode de novo.
  pause
  exit /b 1
)

set "WG=winget install --exact --silent --accept-package-agreements --accept-source-agreements"

call :instalar "Python 3.12" Python.Python.3.12
call :instalar "Node.js LTS" OpenJS.NodeJS.LTS
call :instalar "Git" Git.Git
call :instalar "Ollama" Ollama.Ollama

echo.
echo === Placa de video ===
where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
  echo Driver NVIDIA encontrado. O PyTorch ja traz o CUDA; nao precisa instalar o CUDA Toolkit.
) else (
  echo Driver NVIDIA nao encontrado. Instale o driver mais recente pelo app NVIDIA ^(nvidia.com/drivers^).
)

echo.
echo Pronto. Feche esta janela e de dois cliques em instalar.bat para preparar o projeto.
pause
exit /b 0

:instalar
echo.
echo --- %~1 ---
winget list --exact --id %2 >nul 2>nul
if %errorlevel%==0 (
  echo Ja instalado.
  exit /b 0
)
%WG% --id %2
if %errorlevel%==0 (echo Instalado.) else (echo Nao foi possivel instalar %~1. Veja a mensagem acima.)
exit /b 0
