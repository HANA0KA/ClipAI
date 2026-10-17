"""Huecos en el texto del clip.

El pulido con Whisper a veces se salta un trozo de habla (ruido, música de
fondo, voz baja) que la transcripción de YouTube sí trae: el clip queda con
«un pedazo» del texto. Aquí se detectan esos huecos y se rellenan con las
palabras de la transcripción completa (`transcript.json`).

Un hueco es un tramo de ≥ MIN_GAP s dentro del clip sin ninguna palabra del
pulido donde la transcripción tiene al menos MIN_WORDS palabras. Se toman las
palabras a más de MARGIN s de los bordes del hueco (los tiempos de YouTube
son menos exactos que los de Whisper) para no repetir las de al lado. Misma
lógica en `web/lib/gapfill.ts` (deben coincidir).
"""
from __future__ import annotations

import re

MIN_GAP = 2.5
MARGIN = 0.35
MIN_WORDS = 2
_NOISE = re.compile(r"^[\[(♪].*[\])♪]$|^♪+$")  # «[Música]», «(aplausos)», «♪»


def is_noise(word: str) -> bool:
    return bool(_NOISE.match((word or "").strip()))


def _mid(w: dict) -> float:
    return (w["start"] + w["end"]) / 2


def candidates(words: list[dict], source: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Palabras de ``source`` que faltan en ``words`` dentro de ``ranges``
    (tramos [inicio, fin) del video fuente), en orden."""
    have = {round(w["start"] * 1000) for w in words}
    out: dict[int, dict] = {}
    for a, b in ranges:
        inside = sorted((w for w in words if a <= _mid(w) < b and str(w.get("w", "")).strip()),
                        key=lambda w: w["start"])
        # (inicio, fin, ¿es una palabra?): el margen solo va contra palabras vecinas, no contra los
        # bordes del clip (ahí no hay nada que duplicar).
        edges = [(w["start"], w["end"], True) for w in inside] + [(b, b, False)]
        reach, prev_word = a, False
        for start, end, is_word in edges:
            if start - reach >= MIN_GAP:
                lo = reach + (MARGIN if prev_word else 0.0)
                hi = start - (MARGIN if is_word else 0.0)
                got = [x for x in source if lo <= _mid(x) <= hi and not is_noise(x["w"])
                       and str(x.get("w", "")).strip() and round(x["start"] * 1000) not in have]
                if len(got) >= MIN_WORDS:
                    for x in got:
                        out[round(x["start"] * 1000)] = x
            if end >= reach:
                reach, prev_word = end, is_word
    return [out[k] for k in sorted(out)]


def fill(words: list[dict], source: list[dict], ranges: list[tuple[float, float]]) -> tuple[list[dict], int]:
    """(palabras con los huecos rellenos, cuántas se añadieron)."""
    extra = candidates(words, source, ranges)
    if not extra:
        return words, 0
    merged = [*words, *({"w": x["w"], "start": x["start"], "end": x["end"]} for x in extra)]
    return sorted(merged, key=lambda w: w["start"]), len(extra)


__all__ = ["candidates", "fill", "is_noise", "MIN_GAP", "MARGIN", "MIN_WORDS"]
