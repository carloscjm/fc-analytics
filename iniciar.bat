@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist backend\.venv (
  echo Rode o instalar.bat primeiro.
  pause
  exit /b 1
)

echo Iniciando o backend (porta 8000) e o frontend (porta 5173) ...
rem Antes de subir o backend, instala bibliotecas novas que as atualizacoes trazem (rapido quando ja esta tudo instalado).
start "FC Analytics - backend" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && python -m pip install -q --disable-pip-version-check -r requirements.txt && python -m pip install -q --disable-pip-version-check --no-deps rapidocr==3.9.2 && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
rem npm install no inicio: instala bibliotecas novas que as atualizacoes trazem.
start "FC Analytics - frontend" cmd /k "cd /d %~dp0frontend && npm install --no-audit --no-fund --loglevel=error && npm run dev"

timeout /t 4 /nobreak >nul
start "" http://localhost:5173
