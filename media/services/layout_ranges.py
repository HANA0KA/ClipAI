"""Qué tramos del clip usan qué diseño (sidecar `<clip>.layout.json`).

Adaptado de OpenShorts — https://github.com/mutonby/openshorts
Ruta original: layout_ranges.py (write, read, normalise, split_ranges, in_split).
Copyright (c) 2024 OpenShorts — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: rutas con pathlib y escritura atómica; sin `remap` (no hay rerender
por concatenación).

Los tiempos están en la línea de tiempo del clip, la misma de los subtítulos.
En los tramos SPLIT el generador ASS centra las palabras en la unión (\\an5).
"""
from __future__ import annotations

from pathlib import Path

from media.services.atomic import read_json, write_json

SIDECAR_SUFFIX = ".layout.json"


def sidecar_path(video_path: Path) -> Path:
    return Path(str(video_path) + SIDECAR_SUFFIX)


def normalise(ranges) -> list[dict]:
    out = []
    for r in ranges or []:
        try:
            if isinstance(r, dict):
                s, e, layout = r["start"], r["end"], r.get("layout", "")
            else:
                s, e, layout = r
            s, e = float(s), float(e)
        except (KeyError, TypeError, ValueError):
            continue
        if e > s:
            out.append({"start": round(s, 3), "end": round(e, 3), "layout": str(layout).lower()})
    return out


def write(video_path: Path, ranges) -> list[dict]:
    payload = normalise(ranges)
    try:
        write_json(sidecar_path(video_path), {"ranges": payload})
    except OSError:
        pass  # un sidecar perdido nunca debe tumbar un render que salió bien
    return payload


def read(video_path: Path) -> list[dict]:
    data = read_json(sidecar_path(video_path), default={}) or {}
    return normalise(data.get("ranges"))


def split_ranges(ranges) -> list[tuple[float, float]]:
    return [(r["start"], r["end"]) for r in normalise(ranges) if r["layout"] == "split"]


def in_split(t: float, splits) -> bool:
    return any(s <= t < e for s, e in splits or [])


def shift(ranges, offset: float) -> list[dict]:
    """Desplaza los tramos (p. ej. al anteponer la frase más fuerte)."""
    return normalise([{**r, "start": r["start"] + offset, "end": r["end"] + offset}
                      for r in normalise(ranges)])
