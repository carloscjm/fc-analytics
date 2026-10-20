@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === FC Analytics: instalacao das dependencias ===
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3.12"
) else (
  set "PY=python"
)

echo [1/3] Criando ambiente Python em backend\.venv ...
if not exist backend\.venv (
  %PY% -m venv backend\.venv || goto :erro
)
call backend\.venv\Scripts\activate.bat || goto :erro
python -m pip install --upgrade pip >nul
pip install -r backend\requirements-dev.txt || goto :erro

echo.
echo [2/3] Instalando dependencias do frontend ...
pushd frontend
call npm install || (popd & goto :erro)
popd

echo.
echo [3/3] Conferindo o ambiente ...
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
