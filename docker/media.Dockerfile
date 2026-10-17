# Servicio de procesamiento (FastAPI + worker). Contexto de construcción: la raíz del repo.
FROM python:3.11-slim-trixie
# ffmpeg 7 de Debian trixie trae libass y libx264 (el 5.1 de bookworm falla con loudnorm+aresample); Noto Color Emoji lo usan los emojis del video.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-color-emoji libgl1 libglib2.0-0 curl tini \
    && rm -rf /var/lib/apt/lists/*
# yt-dlp necesita un entorno JavaScript para YouTube.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# PyTorch en su versión de CPU (la de PyPI en Linux x86 arrastra CUDA, ≈ 3 GB más).
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY media/requirements.txt media/requirements.txt
RUN pip install -r media/requirements.txt

COPY media/ media/
COPY pytest.ini .
# Las pruebas crean su BD con las migraciones de Prisma.
COPY web/prisma/migrations web/prisma/migrations
COPY docker/media-entrypoint.sh /usr/local/bin/media-entrypoint
RUN chmod +x /usr/local/bin/media-entrypoint \
    && mkdir -p /app/data /app/db && chown 1000:1000 /app/data /app/db
# HOME se queda en /tmp (se corre con el UID del usuario, que no tiene carpeta propia). Todo lo
# que pesa o se acumula (temporales de ffmpeg/yt-dlp, cachés, modelos de Whisper y embeddings)
# va al volumen de datos: la capa del contenedor vive en el disco de la VM de Docker, que suele
# ser pequeño, y el volumen de datos es tu disco.
ENV HOME=/tmp \
    TMPDIR=/app/data/cache/tmp \
    XDG_CACHE_HOME=/app/data/cache/xdg \
    MPLCONFIGDIR=/app/data/cache/xdg/matplotlib \
    TORCHINDUCTOR_CACHE_DIR=/app/data/cache/xdg/torchinductor \
    HF_HOME=/app/data/cache/huggingface \
    FFMPEG_BIN= FFPROBE_BIN=
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "media-entrypoint"]
