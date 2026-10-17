"""Peticiones de cancelación entre la API y el hilo de trabajo (en memoria).

La API marca ``render:<clip>`` y el render lo consulta en cada cuadro del
reencuadre y en cada línea de progreso de ffmpeg; al verlo, corta el
subproceso y lanza StopRequested. El MP4 anterior (si había) queda intacto
porque el nuevo se escribe en un temporal.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_flags: set[str] = set()


def request(key: str) -> None:
    with _lock:
        _flags.add(key)


def clear(key: str) -> None:
    with _lock:
        _flags.discard(key)


def requested(key: str) -> bool:
    with _lock:
        return key in _flags


def render_key(clip_id: str) -> str:
    return f"render:{clip_id}"


__all__ = ["request", "clear", "requested", "render_key"]
