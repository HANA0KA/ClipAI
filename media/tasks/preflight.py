"""Revisión previa antes de gastar (plan 6.8): duración, disco y tokens.

Idea de ClipPyMe `pipeline/preflight.py`, reescrita a lo que usa ClipAI.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from media.config import settings
from media.errors import PermanentError

# Del orden de 1 GB por hora a 1080p en H.264 + audio WAV mono 16 kHz (~115 MB/h).
BYTES_PER_SECOND = 330_000


def estimate_tokens(duration_sec: float) -> int:
    """Palabras habladas (~2,4/s) → tokens (~1,5 por palabra) + prompt."""
    return int(duration_sec * 2.4 * 1.5) + 4_000


def check(duration_sec: float | None, folder: Path, *, is_live: bool = False) -> dict:
    s = settings()
    if is_live:
        raise PermanentError("Es una transmisión en directo; espera a que termine y vuelve a intentarlo.")
    if duration_sec is not None:
        if duration_sec <= 0:
            raise PermanentError("No se pudo leer la duración del video.")
        if duration_sec < s.clip_min_sec:
            raise PermanentError(f"El video dura {duration_sec:.0f} s: menos que un clip ({s.clip_min_sec:.0f} s).")
        if duration_sec > s.max_video_minutes * 60:
            raise PermanentError(
                f"El video dura {duration_sec / 60:.0f} min; el máximo es {s.max_video_minutes} min (MAX_VIDEO_MINUTES).")
    folder.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(folder).free / 1024 ** 3
    need_gb = (duration_sec or 3600) * BYTES_PER_SECOND * 1.5 / 1024 ** 3 + s.min_free_disk_gb
    if free_gb < need_gb:
        raise PermanentError(f"Espacio libre insuficiente: {free_gb:.1f} GB (hacen falta ~{need_gb:.1f} GB).")
    tokens = estimate_tokens(duration_sec or 0)
    return {"free_gb": round(free_gb, 1), "need_gb": round(need_gb, 1), "est_tokens": tokens}
