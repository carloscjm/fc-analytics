@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === FC Analytics: instalacao das dependencias ===
echo Pode levar alguns minutos na primeira vez (o PyTorch com CUDA tem alguns GB).
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3.12"
) else (
  set "PY=python"
)

echo [1/4] Criando ambiente Python em backend\.venv ...
if not exist backend\.venv (
  %PY% -m venv backend\.venv || goto :erro
)
call backend\.venv\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul

echo.
echo [2/4] Instalando o PyTorch ...
where nvidia-smi >nul 2>nul
if not %errorlevel%==0 goto :torch_cpu

set "DRV=0"
for /f "tokens=1 delims=." %%v in ('nvidia-smi --query-gpu^=driver_version --format^=csv^,noheader') do set "DRV=%%v"
rem CUDA 13.0 pede driver 580 ou mais novo; com driver antigo usamos CUDA 12.6.
if %DRV% GEQ 580 (
  set "CU=cu130"
) else (
  set "CU=cu126"
  echo Seu driver NVIDIA e antigo ^(versao %DRV%^). Vale atualizar pelo app NVIDIA; por enquanto, usando CUDA 12.6.
)
echo GPU NVIDIA encontrada: instalando o PyTorch com %CU%.
pip install torch torchvision --index-url https://download.pytorch.org/whl/%CU% || goto :erro
goto :torch_ok

:torch_cpu
echo GPU NVIDIA nao encontrada: instalando a versao para CPU.
pip install torch torchvision || goto :erro

:torch_ok

echo.
echo [3/4] Instalando as bibliotecas do backend e do frontend ...
pip install -r backend\requirements-dev.txt || goto :erro
pip install --no-deps rapidocr==3.9.2 || goto :erro
pushd frontend
call npm install || (popd & goto :erro)
popd

echo.
echo [4/4] Conferindo o ambiente ...
python backend\check_env.py

echo.
echo Instalacao concluida. Para abrir o app, de dois cliques em iniciar.bat
pause
exit /b 0

:erro
echo.
echo Algo deu errado na instalacao. Veja a mensagem acima.
pause
exit /b 1
