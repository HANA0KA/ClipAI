#!/usr/bin/env bash
# ClipAI — arranca FastAPI (127.0.0.1:8000) y Next.js (127.0.0.1:3000) juntos.
#
#   ./start.sh               instala lo que falte, migra la BD, compila y arranca
#   ./start.sh --dev         Next.js en modo desarrollo (recarga en caliente)
#   ./start.sh --no-install  no instala dependencias (arranque rápido)
#
# Ctrl+C detiene los dos servicios.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.deno/bin:$PATH"

DEV=0
INSTALL=1
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    --no-install) INSTALL=0 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "Opción desconocida: $arg"; exit 1 ;;
  esac
done

say()  { printf '\033[1;33m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!\033[0m %s\n' "$*"; }

# ── Requisitos ───────────────────────────────────────────────────────────────
PY="$(command -v python3.11 || true)"
[ -z "$PY" ] && { warn "Falta Python 3.11 (macOS: brew install python@3.11)"; exit 1; }
command -v node >/dev/null || { warn "Falta Node.js LTS (macOS: brew install node)"; exit 1; }
command -v ffmpeg >/dev/null || [ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ] || {
  warn "Falta FFmpeg (macOS: brew install ffmpeg-full)"; exit 1; }
command -v deno >/dev/null || warn "Falta Deno: yt-dlp lo necesita para YouTube (macOS: brew install deno)"
if ! [ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ] && ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q " ass "; then
  warn "Tu ffmpeg no tiene libass: los subtítulos no se podrán quemar (macOS: brew install ffmpeg-full)"
fi

[ -f .env ] || { cp .env.example .env; say "Creado .env a partir de .env.example (añade tu GEMINI_API_KEY)"; }
mkdir -p data/projects data/logs

# ── Dependencias ─────────────────────────────────────────────────────────────
hash_of() { shasum "$1" | cut -d' ' -f1; }

if [ "$INSTALL" = 1 ]; then
  if [ ! -x .venv/bin/python ]; then
    say "Creando entorno Python (.venv)"
    "$PY" -m venv .venv
  fi
  if [ "$(cat .venv/.req-hash 2>/dev/null)" != "$(hash_of media/requirements.txt)" ]; then
    say "Instalando dependencias de Python (la primera vez tarda unos minutos)"
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r media/requirements.txt
    hash_of media/requirements.txt > .venv/.req-hash
    date +%s > .venv/.ytdlp-updated
  fi
  # yt-dlp cambia a menudo porque YouTube cambia: actualizarlo cada semana (plan 6.1).
  last=$(cat .venv/.ytdlp-updated 2>/dev/null || echo 0)
  if [ $(( $(date +%s) - last )) -gt 604800 ]; then
    say "Actualizando yt-dlp (semanal)"
    .venv/bin/pip install -q -U "yt-dlp[default]" && date +%s > .venv/.ytdlp-updated || warn "No se pudo actualizar yt-dlp"
  fi

  if [ ! -d web/node_modules ] || [ "$(cat web/node_modules/.lock-hash 2>/dev/null)" != "$(hash_of web/package-lock.json)" ]; then
    say "Instalando dependencias de Node"
    (cd web && npm ci --no-audit --no-fund)
    # better-sqlite3 es nativo: se compila aunque npm tenga ignore-scripts=true.
    (cd web && npm rebuild better-sqlite3 --ignore-scripts=false >/dev/null)
    hash_of web/package-lock.json > web/node_modules/.lock-hash
    rm -rf web/.next
  fi
fi

# ── Base de datos ────────────────────────────────────────────────────────────
say "Aplicando migraciones de la base de datos"
(cd web && npx prisma migrate deploy >/dev/null && npx prisma generate >/dev/null)

# ── Compilación de la interfaz ───────────────────────────────────────────────
if [ "$DEV" = 0 ]; then
  newest_src=$(find web/app web/components web/lib web/prisma -type f -newer web/.next/BUILD_ID 2>/dev/null | head -1 || true)
  if [ ! -f web/.next/BUILD_ID ] || [ -n "$newest_src" ]; then
    say "Compilando la interfaz (next build)"
    (cd web && npm run build >/dev/null)
  fi
fi

# ── Arranque ─────────────────────────────────────────────────────────────────
# Solo los puertos: no se hace `source .env` para no pisar variables que ya
# tengas en tu shell (p. ej. GEMINI_API_KEY) con valores vacíos del archivo.
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' || true; }
MEDIA_PORT="$(env_value MEDIA_PORT)"; MEDIA_PORT="${MEDIA_PORT:-8000}"
WEB_PORT="$(env_value WEB_PORT)"; WEB_PORT="${WEB_PORT:-3000}"

for port in "$MEDIA_PORT" "$WEB_PORT"; do
  if lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "El puerto $port ya está en uso (¿ClipAI ya está abierto?). Ciérralo e inténtalo de nuevo."
    exit 1
  fi
done

pids=()
cleanup() {
  trap - INT TERM EXIT
  say "Deteniendo ClipAI"
  for pid in ${pids[@]+"${pids[@]}"}; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "Servicio de procesamiento en http://127.0.0.1:$MEDIA_PORT"
# MediaPipe (C++/absl) escribe avisos de arranque inofensivos en stderr que no se
# pueden silenciar desde Python; se filtran solo esas líneas conocidas.
MEDIAPIPE_NOISE='^(WARNING: All log messages before absl::InitializeLog|[IW][0-9]{4} [0-9:.]+ +[0-9]+ (gl_context|inference_feedback_manager)\.cc|INFO: Created TensorFlow Lite XNNPACK delegate)'
.venv/bin/uvicorn media.main:app --host 127.0.0.1 --port "$MEDIA_PORT" --log-level warning \
  2> >(grep --line-buffered -vE "$MEDIAPIPE_NOISE" >&2) &
pids+=($!)

say "Interfaz en http://127.0.0.1:$WEB_PORT"
if [ "$DEV" = 1 ]; then
  (cd web && exec npx next dev -H 127.0.0.1 -p "$WEB_PORT") &
else
  (cd web && exec npx next start -H 127.0.0.1 -p "$WEB_PORT") &
fi
pids+=($!)

# Abre el navegador cuando la interfaz responde (solo macOS).
(
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$WEB_PORT"; then
      command -v open >/dev/null && open "http://127.0.0.1:$WEB_PORT"
      break
    fi
    sleep 1
  done
) &

# Si cualquiera de los dos termina, se detiene el otro (bash 3.2 de macOS no tiene `wait -n`).
while kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; do sleep 2; done
