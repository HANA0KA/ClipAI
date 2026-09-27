"""Corte inteligente opcional: quitar silencios largos y muletillas (plan 6.6.5).

Escrito desde cero (ClipPyMe usa el binario auto-editor; aquí basta ffmpeg):
se calculan los tramos a conservar y se aplican con `select`/`aselect` en la
misma pasada del render, DESPUÉS de quemar los subtítulos (orden del plan:
recorte → reencuadre → subtítulos → corte inteligente → gancho → audio), así
el texto no se desfasa.
"""
from __future__ import annotations

import re

FILLERS = frozenset({"eh", "ehh", "em", "emm", "mm", "mmm", "hmm", "um", "umm", "uh", "uhm", "ah", "ahh"})


def _norm(w: str) -> str:
    return re.sub(r"[^\wáéíóúñü]", "", (w or "").lower())


def keep_segments(duration: float, silences: list[tuple[float, float]], words: list[dict] | None = None,
                  *, min_silence: float = 0.6, margin: float = 0.15,
                  min_keep: float = 0.25) -> list[tuple[float, float]]:
    """Tramos [s, e) a conservar, en segundos del clip.

    Se quitan los silencios de al menos ``min_silence`` dejando ``margin`` a
    cada lado (las pausas cortas dramáticas se respetan) y las muletillas
    aisladas («eh», «um»…) detectadas en las palabras.
    """
    cuts: list[tuple[float, float]] = []
    for s, e in silences or []:
        if e - s >= min_silence:
            a, b = s + margin, e - margin
            if b - a > 0.05:
                cuts.append((max(0.0, a), min(duration, b)))
    for w in words or []:
        if _norm(w.get("w", "")) in FILLERS:
            cuts.append((max(0.0, w["start"] - 0.03), min(duration, w["end"] + 0.03)))
    if not cuts:
        return [(0.0, duration)]
    cuts.sort()
    merged: list[list[float]] = []
    for a, b in cuts:
        if merged and a <= merged[-1][1] + 0.02:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep, t = [], 0.0
    for a, b in merged:
        if a - t >= min_keep:
            keep.append((round(t, 3), round(a, 3)))
        t = max(t, b)
    if duration - t >= min_keep:
        keep.append((round(t, 3), round(duration, 3)))
    return keep or [(0.0, duration)]


def kept_duration(segments: list[tuple[float, float]]) -> float:
    return sum(e - s for s, e in segments)


def select_expr(segments: list[tuple[float, float]]) -> str:
    # Dentro de comillas simples del filtergraph las comas no separan filtros.
    return "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in segments)


def video_filter(segments: list[tuple[float, float]]) -> str:
    return f"select='{select_expr(segments)}',setpts=N/FRAME_RATE/TB"


def audio_filter(segments: list[tuple[float, float]]) -> str:
    return f"aselect='{select_expr(segments)}',asetpts=N/SR/TB"
