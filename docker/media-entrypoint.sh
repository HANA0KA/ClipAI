#!/bin/sh
# Arranca el servicio de procesamiento en :8000 (solo accesible desde la red de Compose).
set -eu
mkdir -p /app/data/projects "$TMPDIR" "$XDG_CACHE_HOME" "$MPLCONFIGDIR" "$HF_HOME"

# YouTube cambia a menudo: yt-dlp se actualiza en cada arranque (si hay red) a una carpeta
# temporal que tiene prioridad sobre la versión de la imagen. Si falla, se usa la de la imagen.
if timeout 90 pip install -q -U --target /app/data/cache/ytdlp "yt-dlp[default]" >/dev/null 2>&1; then
  export PYTHONPATH="/app/data/cache/ytdlp${PYTHONPATH:+:$PYTHONPATH}"
  echo "▸ yt-dlp $(python -m yt_dlp --version)"
else
  echo "! No se pudo actualizar yt-dlp; se usa la versión de la imagen"
fi

exec uvicorn media.main:app --host 0.0.0.0 --port 8000 --log-level warning
