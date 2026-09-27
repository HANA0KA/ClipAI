"""TextTiling léxico (sin IA): segmentación temática de la transcripción.

Copiado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/texttiling_ops.py (portado a su vez de
ClipsAI `clip/texttiler.py`, MIT).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: stopwords en español añadidas; se quita `find_topic_clips` (los
candidatos los genera `services/candidates.py` según el plan 6.3).

Se usa como respaldo de `services/segmentation.py` cuando el modelo de
embeddings no está disponible (EMBEDDINGS_ENABLED=0 o sin descarga).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

# Small multilingual stop-word set (EN + IT de ClippyMe; ES añadido para ClipAI).
# Dropping these sharpens lexical-cohesion signal: function words co-occur in
# every block and would otherwise wash out the topic-specific term overlap.
_STOPWORDS = frozenset(
    """
    a an the of to in is it and or but for on at by with as be this that these those
    i you he she we they me him her us them my your his our their its do does did not
    no yes so if then than too very can will just have has had was were are am been
    il lo la i gli le un uno una di a da in con su per tra fra e o ma se che non
    è sono ho hai ha abbiamo avete hanno questo questa questi queste quello quella
    mi ti ci vi si come anche più meno molto poco
    el los las del al un una unos unas y o pero que en de con por para como más
    es son fue ser está están estoy era hay muy ya lo le les se su sus mi mis tu tus
    yo tú él ella nosotros ellos esto eso esta ese este aquí ahí sí también porque
    cuando donde qué cómo entonces pues bueno tan todo todos nada algo
    """.split()
)

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)  # unicode letters, no digits/punct


def tokenize(text: str) -> List[str]:
    """Lower-case unicode word tokens with stop-words removed."""
    return [t for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")) if t not in _STOPWORDS]


def _cosine(a: Counter, b: Counter) -> float:
    """Cosine similarity of two term-frequency Counters (0.0 if either empty)."""
    if not a or not b:
        return 0.0
    # iterate the smaller dict
    if len(a) > len(b):
        a, b = b, a
    dot = sum(cnt * b.get(term, 0) for term, cnt in a.items())
    if dot == 0:
        return 0.0
    na = math.sqrt(sum(c * c for c in a.values()))
    nb = math.sqrt(sum(c * c for c in b.values()))
    return dot / (na * nb)


def gap_scores(block_tokens: Sequence[Sequence[str]], k: int) -> List[float]:
    """Cosine similarity across each gap between consecutive blocks.

    For gap ``i`` (between block ``i`` and ``i+1``) the left window pools the
    token counts of blocks ``[i-k+1 .. i]`` and the right window pools
    ``[i+1 .. i+k]`` (clamped to the ends), mirroring ClipsAI's ``k``-window
    pooling but with bag-of-words term frequencies instead of pooled embeddings.
    Returns ``len(block_tokens) - 1`` scores (empty if fewer than 2 blocks).
    """
    n = len(block_tokens)
    if n < 2:
        return []
    k = max(1, k)
    scores: List[float] = []
    for i in range(n - 1):
        left = Counter()
        for j in range(max(0, i - k + 1), i + 1):
            left.update(block_tokens[j])
        right = Counter()
        for j in range(i + 1, min(n, i + 1 + k)):
            right.update(block_tokens[j])
        scores.append(_cosine(left, right))
    return scores


def smooth_scores(scores: Sequence[float], width: int) -> List[float]:
    """Centered flat (moving-average) smoothing, faithful to TextTiling's smooth().

    ``width`` < 3 (or longer than the series) is a no-op. Window is normalized
    and applied with edge clamping so the series length is preserved.
    """
    n = len(scores)
    if width < 3 or n < width:
        return list(scores)
    half = width // 2
    out: List[float] = []
    for i in range(n):
        lo, hi = i - half, i + half
        acc = 0.0
        for j in range(lo, hi + 1):
            jj = 0 if j < 0 else (n - 1 if j >= n else j)  # clamp edges
            acc += scores[jj]
        out.append(acc / (2 * half + 1))
    return out


def depth_scores(gaps: Sequence[float]) -> List[float]:
    """Valley depth at each gap: ``(left_peak - gap) + (right_peak - gap)``.

    Peaks are found by walking outward while scores are non-decreasing, exactly
    as in ClipsAI's ``_calc_depth_scores``. A deep valley (low similarity flanked
    by high-similarity peaks) marks a strong topic boundary.
    """
    n = len(gaps)
    depths: List[float] = [0.0] * n
    for i in range(n):
        lpeak = gaps[i]
        j = i
        while j - 1 >= 0 and gaps[j - 1] >= lpeak:
            lpeak = gaps[j - 1]
            j -= 1
        rpeak = gaps[i]
        j = i
        while j + 1 < n and gaps[j + 1] >= rpeak:
            rpeak = gaps[j + 1]
            j += 1
        depths[i] = (lpeak - gaps[i]) + (rpeak - gaps[i])
    return depths


def _cutoff(depths: Sequence[float], policy: str) -> float:
    n = len(depths)
    if n == 0:
        return 0.0
    mean = sum(depths) / n
    var = sum((d - mean) ** 2 for d in depths) / n
    std = math.sqrt(var)
    if policy == "average":
        return mean
    if policy == "low":
        return mean - std
    return mean + std  # "high" (default)


def identify_boundaries(depths: Sequence[float], cutoff_policy: str = "high") -> List[int]:
    """Gap indices that are local depth maxima above the cutoff.

    A gap ``i`` is a boundary when ``depth > cutoff`` AND it is ``>=`` both
    neighbours AND it is not a flat plateau equal to both neighbours — the exact
    four-condition test from ClipsAI's ``_identify_boundaries``. The returned
    indices are *gap* indices, i.e. a boundary at ``i`` means "split after block i".
    """
    n = len(depths)
    if n == 0:
        return []
    cutoff = _cutoff(depths, cutoff_policy)
    out: List[int] = []
    for i in range(n):
        left = depths[i - 1] if i > 0 else float("-inf")
        right = depths[i + 1] if i < n - 1 else float("-inf")
        if (
            depths[i] > cutoff
            and depths[i] >= left
            and depths[i] >= right
            and not (depths[i] == left and depths[i] == right)
        ):
            out.append(i)
    return out


def segment_indices(
    block_tokens: Sequence[Sequence[str]],
    k: int = 7,
    smoothing_width: int = 3,
    cutoff_policy: str = "high",
) -> List[Tuple[int, int]]:
    """Group blocks into topic segments → list of inclusive ``(start, end)`` block-index spans.

    Runs the full lexical TextTiling chain (gap → smooth → depth → boundaries)
    and converts the gap boundaries into contiguous block spans covering every
    block. ``k`` is auto-shrunk when the series is short (``> n/5`` is clamped),
    mirroring ClipsAI's guard so tiny transcripts still produce a sane result.
    """
    n = len(block_tokens)
    if n <= 1:
        return [(0, n - 1)] if n == 1 else []
    if k > max(1, n // 5):
        k = max(1, n // 5)
    gaps = gap_scores(block_tokens, k)
    gaps = smooth_scores(gaps, smoothing_width)
    depths = depth_scores(gaps)
    bounds = identify_boundaries(depths, cutoff_policy)
    spans: List[Tuple[int, int]] = []
    start = 0
    for b in bounds:
        spans.append((start, b))  # gap b → split after block b
        start = b + 1
    if start <= n - 1:
        spans.append((start, n - 1))
    return spans
