@echo off
REM ClipAI — arranca FastAPI (127.0.0.1:8000) y Next.js (127.0.0.1:3000) en Windows.
REM Requisitos: Python 3.11, Node.js LTS, FFmpeg con libass (build "full" de gyan.dev) y Deno en el PATH.
setlocal
cd /d "%~dp0"

where py >nul 2>nul || (echo Falta Python 3.11 & exit /b 1)
where node >nul 2>nul || (echo Falta Node.js & exit /b 1)
where ffmpeg >nul 2>nul || (echo Falta FFmpeg & exit /b 1)
where deno >nul 2>nul || echo Aviso: falta Deno, yt-dlp lo necesita para YouTube

if not exist .env copy .env.example .env >nul
if not exist data\projects mkdir data\projects

if not exist .venv\Scripts\python.exe (
  echo Creando entorno Python...
  py -3.11 -m venv .venv
  .venv\Scripts\pip install -q -r media\requirements.txt || exit /b 1
)
if not exist web\node_modules (
  echo Instalando dependencias de Node...
  pushd web & call npm ci --no-audit --no-fund & call npm rebuild better-sqlite3 --ignore-scripts=false & popd
)

pushd web
call npx prisma migrate deploy >nul || (popd & exit /b 1)
call npx prisma generate >nul
if not exist .next\BUILD_ID call npm run build
popd

echo Servicio de procesamiento en http://127.0.0.1:8000
start "ClipAI media" /b .venv\Scripts\uvicorn media.main:app --host 127.0.0.1 --port 8000 --log-level warning
echo Interfaz en http://127.0.0.1:3000
start "" http://127.0.0.1:3000
pushd web
call npx next start -H 127.0.0.1 -p 3000
popd
