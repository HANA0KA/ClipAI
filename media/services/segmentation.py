"""Segmentación temática de las frases (plan 6.3, paso 2).

TextTiling con embeddings: cada frase → vector con un modelo multilingüe local
(`paraphrase-multilingual-MiniLM-L12-v2`); se comparan bloques de k frases a
cada lado de cada punto y se corta donde la similitud cae por debajo de
media − 1 desviación y es un mínimo local. Los capítulos del video son cortes
obligatorios. Si el modelo no está disponible se usa el TextTiling léxico de
`texttiling_ops` (ClipPyMe).
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from media.config import settings
from media.services import texttiling_ops

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


def _encoder():
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            name = settings().embeddings_model
            try:  # caché local primero: sin consultas a Hugging Face en cada arranque
                _model = SentenceTransformer(name, device="cpu", local_files_only=True)
            except Exception:  # primera vez: se descarga
                _model = SentenceTransformer(name, device="cpu")
        return _model


def embed(texts: list[str]) -> np.ndarray | None:
    """Embeddings normalizados, o None si el modelo no está disponible."""
    if not texts or not settings().embeddings_enabled:
        return None
    try:
        return np.asarray(_encoder().encode(texts, normalize_embeddings=True, batch_size=64,
                                            show_progress_bar=False))
    except Exception as exc:  # sin red en la primera descarga, sin torch, etc.
        log.warning("embeddings no disponibles (%s); se usa TextTiling léxico", exc)
        return None


def embedding_cuts(e: np.ndarray, k: int = 6) -> list[int]:
    """Índices de frase donde empieza un tema nuevo (pura, testeable)."""
    n = len(e)
    if n < 2 * k + 3:
        return []
    sims = np.array([float(e[i - k:i].mean(0) @ e[i:i + k].mean(0)) for i in range(k, n - k)])
    if len(sims) < 3:
        return []
    thr = sims.mean() - sims.std()
    return sorted(i + k for i in range(1, len(sims) - 1)
                  if sims[i] < thr and sims[i] <= sims[i - 1] and sims[i] <= sims[i + 1])


def lexical_cuts(sents: list[dict]) -> list[int]:
    blocks = [texttiling_ops.tokenize(s["text"]) for s in sents]
    spans = texttiling_ops.segment_indices(blocks, k=6, cutoff_policy="average")
    return [b + 1 for (_a, b) in spans[:-1]]


def chapter_cuts(sents: list[dict], chapters) -> set[int]:
    cuts = set()
    for ch in chapters or ():
        t = float(ch.get("start_time") or 0)
        if t <= 0 or not sents:
            continue
        cuts.add(min(range(len(sents)), key=lambda j: abs(sents[j]["start"] - t)))
    cuts.discard(0)
    return cuts


def topic_cuts(sents: list[dict], chapters=(), k: int = 6) -> tuple[list[int], str]:
    """Cortes temáticos + método usado ('embeddings' | 'lexical' | 'none')."""
    if len(sents) < 4:
        return sorted(chapter_cuts(sents, chapters)), "none"
    e = embed([s["text"] for s in sents])
    if e is not None:
        cuts, method = set(embedding_cuts(e, k)), "embeddings"
    else:
        cuts, method = set(lexical_cuts(sents)), "lexical"
    cuts |= chapter_cuts(sents, chapters)
    return sorted(c for c in cuts if 0 < c < len(sents)), method


def topic_of(sent_index: int, cuts: list[int]) -> int:
    """Id del tema = índice de su primera frase."""
    topic = 0
    for c in cuts:
        if c <= sent_index:
            topic = c
        else:
            break
    return topic
