"""Qué tramos del clip usan qué diseño (sidecar `<clip>.layout.json`).

Adaptado de OpenShorts — https://github.com/mutonby/openshorts
Ruta original: layout_ranges.py (write, read, normalise, split_ranges, in_split).
Copyright (c) 2024 OpenShorts — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: rutas con pathlib y escritura atómica; `remap` reescrito para el
recorte rápido del estudio (tramos sacados de un reencuadre ya hecho).

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


def remap(ranges, mapping) -> list[dict]:
    """Tramos de diseño de un video base → video recortado de él.

    ``mapping`` son los tramos ``(inicio, fin)`` del base que forman el nuevo
    video, en orden. Los tramos contiguos del mismo diseño se funden."""
    src = normalise(ranges)
    out: list[dict] = []
    offset = 0.0
    for bs, be in mapping:
        for r in src:
            s, e = max(r["start"], bs), min(r["end"], be)
            if e > s:
                item = {"start": s - bs + offset, "end": e - bs + offset, "layout": r["layout"]}
                if out and out[-1]["layout"] == item["layout"] and abs(out[-1]["end"] - item["start"]) < 1e-3:
                    out[-1]["end"] = item["end"]
                else:
                    out.append(item)
        offset += be - bs
    return normalise(out)
