"""Bordes limpios: palabra → frase → silencio.

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Rutas originales: src/clippyme/pipeline/cut_ops.py (snap_clip_to_words,
_is_sentence_final, sentence_boundaries, snap_clip_to_sentences,
refine_edges_to_silence) y src/clippyme/pipeline/media_probe.py
(parse_silencedetect, detect_silences).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: palabras con clave ``w``; tope de duración configurable (CLIP_MAX_SEC);
abreviaturas en español; el ajuste a silencio nunca mete un borde dentro del
habla; se añade el salto del conector inicial y el ajuste final de duración
(`fit_duration`, propio); sin Smart Cut, fades ni SnapEvent.
"""
from __future__ import annotations

import re
import subprocess
from typing import Iterable

DEFAULT_PRE_PAD = 0.05
DEFAULT_POST_PAD = 0.08
DEFAULT_MAX_SNAP = 0.6
DEFAULT_SENTENCE_BACK = 2.5
DEFAULT_SENTENCE_FWD = 1.5
DEFAULT_MAX_CLIP_DURATION = 150.0
DEFAULT_SILENCE_WINDOW = 1.0
DEFAULT_SILENCE_LEAD = 0.04
DEFAULT_SILENCE_TAIL = 0.06

_SENTENCE_FINAL_CHARS = ".!?…"
_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.",
    "no.", "vol.", "p.", "pp.", "fig.", "inc.", "ltd.", "co.", "e.g.", "i.e.",
    "sra.", "srta.", "ud.", "uds.", "dra.", "lic.", "ing.", "av.", "pág.", "núm.", "aprox.",
})

# Conectores que no deberían abrir un clip.
CONNECTORS = frozenset({
    "y", "e", "entonces", "pero", "pues", "bueno", "además", "osea", "o", "eh", "este", "mmm",
    "and", "so", "but", "also", "um", "uh", "well",
})


# ── Palabras ─────────────────────────────────────────────────────────────────

def _nearest_boundary(target: float, boundaries: Iterable[float], max_snap: float):
    best, best_dist = None, max_snap
    for b in boundaries:
        d = abs(b - target)
        if d <= best_dist:
            best_dist, best = d, b
    return best


def snap_clip_to_words(start: float, end: float, words: list[dict], *,
                       pre_pad: float = DEFAULT_PRE_PAD, post_pad: float = DEFAULT_POST_PAD,
                       max_snap: float = DEFAULT_MAX_SNAP,
                       source_duration: float | None = None) -> tuple[float, float]:
    """Inicio al comienzo de palabra más cercano, fin al final de palabra más
    cercano (dentro de ``max_snap``), con un pequeño margen. Nunca invierte."""
    start, end = float(start), float(end)
    if end <= start:
        return start, end
    new_start, new_end = start, end
    if words:
        s = _nearest_boundary(start, (w["start"] for w in words), max_snap)
        e = _nearest_boundary(end, (w["end"] for w in words), max_snap)
        new_start = s if s is not None else new_start
        new_end = e if e is not None else new_end
    new_start = max(0.0, new_start - pre_pad)
    new_end = new_end + post_pad
    if source_duration is not None:
        new_end = min(new_end, float(source_duration))
    if new_end <= new_start:
        return start, end
    return new_start, new_end


# ── Frases ───────────────────────────────────────────────────────────────────

def _is_sentence_final(word: str) -> bool:
    w = (word or "").strip().rstrip("\"'»)")
    if len(w) < 2 or (w[0] in "([" and w[-1] in ")]"):
        return False
    if w[-1] not in _SENTENCE_FINAL_CHARS:
        return False
    lower = w.lower()
    if lower in _ABBREVIATIONS:
        return False
    core = lower.rstrip(_SENTENCE_FINAL_CHARS)
    if len(core) <= 1 or "." in core or core.replace(",", "").isdigit():
        return False
    return True


def sentence_boundaries(words: list[dict]) -> tuple[list[float], list[float]]:
    """(inicios de frase, finales de frase) a partir de la puntuación."""
    onsets, ends, prev_final = [], [], True
    for w in words:
        if prev_final:
            onsets.append(w["start"])
        if _is_sentence_final(w.get("w", "")):
            ends.append(w["end"])
            prev_final = True
        else:
            prev_final = False
    return onsets, ends


def snap_clip_to_sentences(start: float, end: float, words: list[dict], *,
                           word_start: float, word_end: float,
                           back_budget: float = DEFAULT_SENTENCE_BACK,
                           fwd_budget: float = DEFAULT_SENTENCE_FWD,
                           pre_pad: float = DEFAULT_PRE_PAD, post_pad: float = DEFAULT_POST_PAD,
                           max_duration: float = DEFAULT_MAX_CLIP_DURATION,
                           source_duration: float | None = None) -> tuple[float, float, str]:
    """Inicio hacia atrás al comienzo de frase, fin hacia delante al cierre de
    frase. Degrada a los bordes de palabra si algo no cabe; en transcripciones
    sin puntuación no hace nada."""
    onsets, ends = sentence_boundaries(words) if words else ([], [])
    if not ends:
        onsets = []
    onset = max((o for o in onsets if o <= start and start - o <= back_budget), default=None)
    final = min((x for x in ends if x >= end and x - end <= fwd_budget), default=None)
    sent_start = max(0.0, onset - pre_pad) if onset is not None else None
    sent_end = (final + post_pad) if final is not None else None
    if sent_end is not None and source_duration is not None:
        sent_end = min(sent_end, float(source_duration))

    def _valid(s: float, e: float) -> bool:
        return e > s and (e - s) <= max_duration

    for s in (sent_start, word_start):
        if s is None:
            continue
        for e in (sent_end, word_end):
            if e is None or not _valid(s, e):
                continue
            if s == sent_start and e == sent_end:
                return s, e, "sentence"
            if s == sent_start:
                return s, e, "sentence_start"
            if e == sent_end:
                return s, e, "sentence_end"
            return s, e, "word"
    return (word_start, word_end, "word") if word_end > word_start else (start, end, "word")


def skip_leading_connector(start: float, words: list[dict], max_skip: float = 1.8) -> float:
    """Si el clip abre con conectores («y entonces», «pero»…) salta a la
    primera palabra con contenido, siempre que esté cerca."""
    head = [w for w in words if w["start"] >= start - 0.1][:4]
    k = 0
    while k < len(head) - 1 and re.sub(r"[^\wáéíóúñü]", "", head[k]["w"].lower()) in CONNECTORS:
        k += 1
    if k and head[k]["start"] - start <= max_skip:
        return max(0.0, head[k]["start"] - DEFAULT_PRE_PAD)
    return start


# ── Silencios ────────────────────────────────────────────────────────────────

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def parse_silencedetect(stderr_text: str) -> list[tuple[float, float]]:
    """stderr de ``silencedetect`` → [(inicio, fin)] completos y ordenados."""
    intervals: list[tuple[float, float]] = []
    pending: float | None = None
    for line in (stderr_text or "").splitlines():
        m = _SILENCE_START_RE.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = _SILENCE_END_RE.search(line)
        if m and pending is not None:
            end = float(m.group(1))
            if end > pending:
                intervals.append((max(0.0, pending), end))
            pending = None
    return sorted(intervals)


def detect_silences(media_path: str, ffmpeg: str = "ffmpeg", noise_db: float = -35.0,
                    min_dur: float = 0.15, timeout: int = 900) -> list[tuple[float, float]]:
    """Silencios del audio completo en una pasada. Nunca lanza: [] si falla."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostats", "-i", str(media_path), "-vn",
             "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout)
        return parse_silencedetect(proc.stderr or "")
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []


def refine_edges_to_silence(start: float, end: float, silences: list[tuple[float, float]], *,
                            window: float = DEFAULT_SILENCE_WINDOW, lead: float = DEFAULT_SILENCE_LEAD,
                            tail: float = DEFAULT_SILENCE_TAIL,
                            source_duration: float | None = None,
                            words: list[dict] | None = None) -> tuple[float, float, str]:
    """Acerca cada borde al silencio más cercano dentro de ±window.

    El inicio va al final del silencio que precede al habla y el fin al
    comienzo del silencio que la sigue. Solo se aceptan movimientos que no
    entran en el habla: el inicio (que ya lleva el margen previo de 50 ms) no
    avanza más allá del comienzo de la primera palabra, y el fin solo usa
    silencios que empiezan cuando la última palabra ya terminó.
    """
    start, end = float(start), float(end)
    if end <= start or not silences:
        return start, end, "none"
    new_start, new_end, moved_s, moved_e = start, end, False, False

    words = words or []

    def _speech_between(a: float, b: float) -> bool:
        return any(a - 0.02 <= w["start"] < b for w in words)

    # Inicio: el silencio debe terminar antes de la primera palabra conservada
    # y sin habla entre ambos (p. ej. un conector que ya se saltó).
    first_kept = start + DEFAULT_PRE_PAD - 0.01
    best = min(((abs(e - start), (s, e)) for s, e in silences
                if abs(e - start) <= window and e <= start + 0.05
                and not _speech_between(e, first_kept)), default=None)
    if best is not None:
        s, e = best[1]
        new_start, moved_s = max(s, e - lead), True

    last_kept = end - DEFAULT_POST_PAD + 0.01
    best = min(((abs(s - end), (s, e)) for s, e in silences
                if abs(s - end) <= window and s >= end - 0.1
                and not _speech_between(last_kept, s)), default=None)
    if best is not None:
        s, e = best[1]
        new_end, moved_e = min(e, s + tail), True

    new_start = max(0.0, new_start)
    if source_duration is not None:
        new_end = min(new_end, float(source_duration))
    if new_end <= new_start:
        return start, end, "none"
    path = ("silence" if moved_s and moved_e else "silence_start" if moved_s
            else "silence_end" if moved_e else "none")
    return new_start, new_end, path


def fit_duration(start: float, end: float, words: list[dict], *, lo: float, hi: float,
                 target: float | None = None, source_duration: float | None = None,
                 pre_pad: float = DEFAULT_PRE_PAD,
                 post_pad: float = DEFAULT_POST_PAD) -> tuple[float, float, str]:
    """Lleva la duración del clip a [lo, hi] sin cortar palabras.

    Solo mueve el final (el inicio ya está en el gancho): primero a un cierre
    de frase, si no hay a un final de palabra y, como último recurso, al tope.
    Al alargar se elige el cierre de frase más cercano a ``target``; sin
    ``target`` (duración decidida por la historia) se alarga lo mínimo, sin
    rellenar. Si el video termina antes de llegar a ``lo``, se adelanta el
    inicio a un comienzo de palabra.
    """
    start, end = float(start), float(end)
    limit = float(source_duration) if source_duration is not None else float("inf")
    if lo <= end - start <= hi:
        return start, end, "none"
    target = min(hi, max(lo, target if target is not None else lo))
    _onsets, finals = sentence_boundaries(words) if words else ([], [])
    word_ends = [w["end"] for w in words or []]

    def ends_in(times: list[float], a: float, b: float) -> list[float]:
        return [t + post_pad for t in times if a <= t + post_pad <= b and t + post_pad <= limit]

    if end - start > hi:
        a, b = start + lo, start + hi
        for times, label in ((finals, "trim_sentence"), (word_ends, "trim_word")):
            cands = ends_in(times, a, b)
            if cands:
                return start, round(max(cands), 3), label
        return start, round(min(b, limit), 3), "trim_hard"

    a, b = start + lo, min(start + hi, limit)
    goal = start + target
    cands = ends_in(finals, a, b)
    if cands:
        return start, round(min(cands, key=lambda t: abs(t - goal)), 3), "extend_sentence"
    cands = ends_in(word_ends, a, b)
    if cands:
        return start, round(min(cands), 3), "extend_word"
    if limit - start >= lo:
        return start, round(min(start + lo, limit), 3), "extend_hard"
    # El video se acaba antes: final en la última palabra y se adelanta el inicio.
    last = max((t + post_pad for t in word_ends if t + post_pad <= limit), default=limit)
    new_end = max(min(end, limit), last)
    want = max(0.0, new_end - lo)
    starts = [w["start"] - pre_pad for w in words or [] if w["start"] - pre_pad <= want]
    new_start = max(0.0, max(starts)) if starts else want
    return round(new_start, 3), round(new_end, 3), "extend_start"


def clean_edges(start: float, end: float, words: list[dict], silences: list[tuple[float, float]],
                *, source_duration: float | None = None,
                max_duration: float = DEFAULT_MAX_CLIP_DURATION) -> tuple[float, float, str]:
    """Pipeline completo de un clip: palabra → frase → conector → silencio."""
    ws, we = snap_clip_to_words(start, end, words, source_duration=source_duration)
    s, e, path = snap_clip_to_sentences(start, end, words, word_start=ws, word_end=we,
                                        source_duration=source_duration, max_duration=max_duration)
    s2 = skip_leading_connector(s, words)
    if s2 != s and e - s2 >= 5:
        s, path = s2, path + "+connector"
    s, e, sil = refine_edges_to_silence(s, e, silences, source_duration=source_duration, words=words)
    if sil != "none":
        path += "+" + sil
    return round(s, 3), round(e, 3), path
