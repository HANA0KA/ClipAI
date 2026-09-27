"""Binarios de FFmpeg y ajustes de codificación compartidos.

`video_args()` está adaptado de ClipPyMe `src/clippyme/domain/encode.py`
(`x264_video_args`): todas las pasadas usan el mismo CRF/preset para que las
recodificaciones no acumulen pérdida (plan 6.6.3).

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
