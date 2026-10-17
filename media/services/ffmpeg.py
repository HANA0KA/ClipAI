"""Binarios de FFmpeg y ajustes de codificación compartidos.

`video_args()` está adaptado de ClipPyMe `src/clippyme/domain/encode.py`
(`x264_video_args`): todas las pasadas usan el mismo CRF/preset para que las
recodificaciones no acumulen pérdida.

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/domain/encode.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: variables X264_CRF/X264_PRESET del plan, encoders por hardware,
detección de un ffmpeg con libass.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from media.config import settings

# ffmpeg de Homebrew no trae libass desde 2025; `ffmpeg-full` sí (keg-only).
_CANDIDATES = (
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
)

_VALID_PRESETS = {"ultrafast", "superfast", "veryfast", "faster", "fast",
                  "medium", "slow", "slower", "veryslow"}


class FFmpegError(RuntimeError):
    pass


# Sin metadatos del archivo original en lo que se entrega: un video de celular
# trae la ubicación GPS, el modelo del teléfono y la fecha, y ffmpeg los copia
# por defecto a la salida (comprobado: la ubicación llegaba al MP4 final).
METADATA_SCRUB = ["-map_metadata", "-1", "-map_chapters", "-1",
                  "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1"]

# Techo de pico para loudnorm. −2,0 y no −1,5: el techo se aplica ANTES de
# codificar a AAC y el códec agrega picos entre muestras (medido en clips de
# ClipAI: −1,1 dBTP con −1,5). En una muestra de 14 clips, 1 saturaba con
# −1,5 y ninguno con −2,0 sin perder nivel.
LOUDNORM_TRUE_PEAK = -2.0


def _has_filter(binary: str, name: str) -> bool:
    try:
        out = subprocess.run([binary, "-hide_banner", "-filters"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


@lru_cache(maxsize=1)
def ffmpeg_bin() -> str:
    configured = settings().ffmpeg_bin
    if configured:
        return configured
    candidates = [*_CANDIDATES, shutil.which("ffmpeg") or ""]
    for c in candidates:
        if c and os.path.exists(c) and _has_filter(c, "ass"):
            return c
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


@lru_cache(maxsize=1)
def ffprobe_bin() -> str:
    configured = settings().ffprobe_bin
    if configured:
        return configured
    sibling = Path(ffmpeg_bin()).with_name("ffprobe")
    if sibling.exists():
        return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


@lru_cache(maxsize=1)
def has_libass() -> bool:
    return _has_filter(ffmpeg_bin(), "ass")


def video_args(*, faststart: bool = True, crf: int | None = None, preset: str | None = None) -> list[str]:
    """Argumentos de vídeo de cada pasada (misma calidad en todas)."""
    s = settings()
    encoder = s.video_encoder
    crf = s.x264_crf if crf is None else crf
    if encoder == "h264_videotoolbox":
        # VideoToolbox no tiene CRF: calidad constante aproximada con -q:v.
        args = ["-c:v", "h264_videotoolbox", "-q:v", str(max(1, min(100, 100 - crf * 2))),
                "-profile:v", "high"]
    elif encoder == "h264_nvenc":
        args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    else:
        p = (preset or s.x264_preset).lower()
        args = ["-c:v", "libx264", "-preset", p if p in _VALID_PRESETS else "medium", "-crf", str(crf)]
    args += ["-pix_fmt", "yuv420p"]
    if faststart:
        args += ["-movflags", "+faststart"]
    return args


def lower_priority(proc: subprocess.Popen) -> None:
    """Baja la prioridad de un ffmpeg del render (RENDER_NICE): con el
    estudio abierto, la interfaz tiene la CPU primero; sin competencia el
    render va igual de rápido. Si el sistema no lo permite, no pasa nada."""
    nice = settings().render_nice
    pid = getattr(proc, "pid", None)
    if nice <= 0 or not isinstance(pid, int) or not hasattr(os, "setpriority"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, pid, nice)
    except (OSError, ProcessLookupError):
        pass


def run(args: list[str], *, timeout: float = 1800, what: str = "ffmpeg",
        cwd: Path | str | None = None) -> subprocess.CompletedProcess:
    """Ejecuta ffmpeg/ffprobe; lanza FFmpegError con la cola del stderr si falla."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"{what}: tiempo agotado ({timeout}s)") from exc
    except FileNotFoundError as exc:
        raise FFmpegError(f"{what}: no se encontró el binario {args[0]}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        raise FFmpegError(f"{what} falló ({proc.returncode}): " + " | ".join(tail))
    return proc


def run_progress(args: list[str], *, total: float, on_progress=None, cancelled=None,
                 timeout: float = 3600, what: str = "ffmpeg",
                 cwd: Path | str | None = None) -> None:
    """Como `run`, pero con ``-progress``: informa la fracción hecha
    (``on_progress(0..1)``) y corta el proceso si ``cancelled()`` es True
    (lanza StopRequested). El stderr va a un temporal para no bloquear."""
    import tempfile
    import time

    from media.errors import StopRequested

    cmd = [args[0], "-progress", "pipe:1", "-nostats", *args[1:]]
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, cwd=cwd)
        except FileNotFoundError as exc:
            raise FFmpegError(f"{what}: no se encontró el binario {args[0]}") from exc
        lower_priority(proc)
        last = -1.0
        try:
            for line in proc.stdout:
                if cancelled is not None and cancelled():
                    raise StopRequested("render cancelado")
                if time.monotonic() > deadline:
                    raise FFmpegError(f"{what}: tiempo agotado ({timeout:.0f}s)")
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and on_progress and total > 0:
                    try:
                        frac = max(0.0, min(1.0, int(value) / 1e6 / total))
                    except ValueError:
                        continue
                    if frac - last >= 0.01:
                        last = frac
                        on_progress(frac)
            proc.wait(timeout=120)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise
        if proc.returncode != 0:
            err.seek(0)
            tail = err.read().strip().splitlines()[-12:]
            raise FFmpegError(f"{what} falló ({proc.returncode}): " + " | ".join(tail))


def probe_json(path: Path | str) -> dict:
    import json
    proc = run([ffprobe_bin(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
               timeout=60, what="ffprobe")
    return json.loads(proc.stdout or "{}")


def duration(path: Path | str) -> float:
    try:
        return float(probe_json(path).get("format", {}).get("duration") or 0.0)
    except (FFmpegError, ValueError):
        return 0.0


def video_size(path: Path | str) -> tuple[int, int]:
    """(ancho, alto) mostrados (rotación incluida) del primer stream de video."""
    data = probe_json(path)
    v = next((st for st in data.get("streams") or [] if st.get("codec_type") == "video"), None)
    if not v:
        return 0, 0
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"])) % 180
    if not rot:
        rot = abs(int((v.get("tags") or {}).get("rotate", 0) or 0)) % 180
    return (h, w) if rot == 90 else (w, h)


def extract_audio(src: Path, dst: Path, start: float | None = None, end: float | None = None) -> Path:
    """Audio mono 16 kHz PCM (lo que esperan Whisper y el perfil de energía)."""
    args = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error"]
    if start is not None:
        args += ["-ss", f"{max(0.0, start):.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"] if start is None else ["-t", f"{end - max(0.0, start):.3f}"]
    args += ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    run(args, what="extraer audio")
    return dst
