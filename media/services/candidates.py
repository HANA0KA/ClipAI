"""Candidatos (CLIP_MIN_SEC–CLIP_MAX_SEC, 60–150 s) y señales objetivas.

Funciones puras salvo `audio_profile`, que lee un WAV.
Un candidato es un dict ``{start, end, i, j, topic, source}`` donde ``i``/``j``
son los índices de su primera y última frase.
"""
from __future__ import annotations

import re
import wave
from bisect import bisect_left
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from media.services.segmentation import topic_of

# ── Generación ───────────────────────────────────────────────────────────────


def windows(sents: list[dict], cuts: list[int], lo: float = 30, hi: float = 90,
            max_per_start: int = 6) -> Iterator[dict]:
    """Ventanas dentro de cada tema: empiezan en inicio de frase y terminan en
    final de frase, con duración [lo, hi]. ``max_per_start`` limita cuántos
    finales se prueban por cada inicio (repartidos) para no explotar en videos
    largos sin perder variedad de duración."""
    b = [0, *cuts, len(sents)]
    for a, z in zip(b, b[1:]):
        for i in range(a, z):
            ends = []
            for j in range(i, z):
                d = sents[j]["end"] - sents[i]["start"]
                if d > hi:
                    break
                if d >= lo:
                    ends.append(j)
            if len(ends) > max_per_start:
                idx = np.linspace(0, len(ends) - 1, max_per_start).round().astype(int)
                ends = [ends[k] for k in sorted(set(idx))]
            for j in ends:
                yield {"start": sents[i]["start"], "end": sents[j]["end"], "i": i, "j": j,
                       "topic": a, "source": "window"}


def topic_windows(sents: list[dict], cuts: list[int], lo: float = 30, hi: float = 90) -> list[dict]:
    """Temas completos que ya duran lo..hi."""
    b = [0, *cuts, len(sents)]
    out = []
    for a, z in zip(b, b[1:]):
        if z <= a:
            continue
        d = sents[z - 1]["end"] - sents[a]["start"]
        if lo <= d <= hi:
            out.append({"start": sents[a]["start"], "end": sents[z - 1]["end"], "i": a, "j": z - 1,
                        "topic": a, "source": "topic"})
    return out


def snap_to_sentences(start: float, end: float, sents: list[dict], cuts: list[int],
                      lo: float = 30, hi: float = 90, source: str = "llm") -> dict | None:
    """Lleva un rango libre (propuesta del LLM, pico del heatmap) a bordes de
    frase y lo ajusta a [lo, hi]."""
    if not sents or end <= start:
        return None
    i = min(range(len(sents)), key=lambda k: abs(sents[k]["start"] - start))
    j = min(range(len(sents)), key=lambda k: abs(sents[k]["end"] - end))
    j = max(j, i)
    while j + 1 < len(sents) and sents[j]["end"] - sents[i]["start"] < lo:
        j += 1
    while j > i and sents[j]["end"] - sents[i]["start"] > hi:
        j -= 1
    d = sents[j]["end"] - sents[i]["start"]
    if d < lo * 0.8 or d > hi * 1.05:
        return None
    return {"start": sents[i]["start"], "end": sents[j]["end"], "i": i, "j": j,
            "topic": topic_of(i, cuts), "source": source}


def heatmap_peaks(hm: list[dict] | None, duration: float, min_gap: float = 30.0) -> list[float]:
    """Centros de los picos de «Lo más repetido» (ignorando el primer 5 %)."""
    pts = [p for p in hm or [] if float(p.get("start_time", 0)) > 0.05 * duration]
    if len(pts) < 5:
        return []
    vals = np.array([float(p.get("value", 0)) for p in pts])
    thr = vals.mean() + 0.5 * vals.std()
    peaks = []
    for k in range(len(pts)):
        left = vals[k - 1] if k > 0 else -1
        right = vals[k + 1] if k + 1 < len(pts) else -1
        if vals[k] >= thr and vals[k] >= left and vals[k] >= right:
            peaks.append(((float(pts[k]["start_time"]) + float(pts[k]["end_time"])) / 2, vals[k]))
    peaks.sort(key=lambda p: -p[1])
    chosen: list[float] = []
    for t, _v in peaks:
        if all(abs(t - c) >= min_gap for c in chosen):
            chosen.append(t)
    return chosen[:10]


def heatmap_windows(hm, sents, cuts, duration, lo=30, hi=90) -> list[dict]:
    out = []
    for t in heatmap_peaks(hm, duration):
        c = snap_to_sentences(t - 20, t + 25, sents, cuts, lo, hi, source="heatmap")
        if c:
            out.append(c)
    return out


def dedupe(cands: Iterable[dict]) -> list[dict]:
    """Quita duplicados exactos conservando la fuente más informativa."""
    rank = {"llm": 0, "heatmap": 1, "topic": 2, "window": 3}
    best: dict[tuple, dict] = {}
    for c in cands:
        key = (round(c["start"], 2), round(c["end"], 2))
        if key not in best or rank.get(c["source"], 9) < rank.get(best[key]["source"], 9):
            best[key] = c
    return list(best.values())


# ── Señales (0..1) ───────────────────────────────────────────────────────────


def heat(hm: list[dict] | None, s: float, e: float, dur: float) -> float | None:
    """Intensidad media del heatmap en el rango; None si el video no lo tiene."""
    if not hm:
        return None
    v = [float(p["value"]) for p in hm
         if float(p["end_time"]) > s and float(p["start_time"]) < e
         and float(p["start_time"]) > 0.05 * dur]
    return float(np.mean(v)) if v else 0.0


def audio_profile(wav_path: Path) -> np.ndarray:
    """RMS por segundo en z-scores (1 valor por segundo del video)."""
    with wave.open(str(wav_path), "rb") as wf:
        sr, n, width = wf.getframerate(), wf.getnframes(), wf.getsampwidth()
        raw = wf.readframes(n)
    if width != 2 or not raw:
        return np.zeros(0)
    y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    secs = len(y) // sr
    if secs < 1:
        return np.zeros(0)
    rms = np.sqrt((y[: secs * sr].reshape(secs, sr) ** 2).mean(axis=1))
    return (rms - rms.mean()) / (rms.std() + 1e-9)


def audio(z: np.ndarray, s: float, e: float) -> float:
    """Proporción de segundos con energía > 1,5 desviaciones (risas, énfasis)."""
    seg = z[int(s):int(e)] if len(z) else z
    return float((seg > 1.5).mean()) if len(seg) else 0.0


def _slice(words: list[dict], s: float, e: float) -> list[dict]:
    """Palabras que empiezan en [s, e) (palabras ordenadas: búsqueda binaria;
    con clips de hasta 150 s hay miles de candidatos)."""
    i = bisect_left(words, s, key=lambda w: w["start"])
    j = bisect_left(words, e, key=lambda w: w["start"])
    return words[i:j]


def density(words: list[dict], s: float, e: float) -> float:
    """Palabras por segundo normalizadas; los silencios largos restan."""
    ws = _slice(words, s, e)
    dur = max(1e-6, e - s)
    if not ws:
        return 0.0
    wps = len(ws) / dur
    long_gaps = sum(max(0.0, b["start"] - a["end"] - 1.0) for a, b in zip(ws, ws[1:]))
    return float(max(0.0, min(1.0, wps / 3.0) * (1.0 - min(1.0, long_gaps / dur))))


HOOK_PLUS = re.compile(
    r"\?|¿|\d|\b(tú|te|tu|usted|nadie|nunca|jamás|error|secreto|verdad|por qué|cómo|increíble|"
    r"you|your|never|nobody|secret|truth|mistake|why|how)\b", re.IGNORECASE)
HOOK_MINUS = re.compile(
    r"^(y|entonces|pero|o sea|eso|esto|lo que dije|además|bueno|pues|and|so|but|that|also|um|uh|eh)\b",
    re.IGNORECASE)


def hook_rule(words: list[dict], s: float) -> float:
    """Reglas sobre los primeros 3 s del clip."""
    first = " ".join(w["w"] for w in _slice(words, s, s + 3)).lower().strip(" ,.")
    if not first:
        return 0.2
    score = 0.5 + 0.15 * len(HOOK_PLUS.findall(first)) - 0.4 * bool(HOOK_MINUS.match(first))
    return max(0.0, min(1.0, score))


def pause_before(words: list[dict], s: float) -> float:
    """Pausa antes de la primera frase del clip: una entrada limpia (el orador
    calla ≥ 1 s y arranca una idea nueva) vale 1; de 0,5 a 1 s vale 0,5."""
    i = bisect_left(words, s - 0.15, key=lambda w: w["start"])  # palabras ordenadas
    if i >= len(words):
        return 0.0
    gap = words[i]["start"] - (words[i - 1]["end"] if i > 0 else 0.0)
    if gap >= 1.0:
        return 1.0
    return 0.5 if gap >= 0.5 else 0.0


def signals_for(c: dict, words: list[dict], hm, audio_z: np.ndarray, duration: float) -> dict:
    return {
        "heat": heat(hm, c["start"], c["end"], duration),
        "audio": audio(audio_z, c["start"], c["end"]),
        "density": density(words, c["start"], c["end"]),
        "hook": hook_rule(words, c["start"]),
        "pause": pause_before(words, c["start"]),
    }
