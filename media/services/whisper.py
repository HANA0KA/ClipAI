"""Transcripción local con marcas por palabra.

faster-whisper por defecto (CPU/Apple Silicon, `large-v3-turbo` + `int8`); WhisperX si
WHISPER_ENGINE=whisperx y está instalado (GPU NVIDIA, alineación forzada).
El modelo se carga una sola vez por proceso.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

from media.config import settings
from media.services.transcript import merge_continuations

log = logging.getLogger(__name__)
_lock = threading.Lock()
_model = None
_model_key = None


def _faster_whisper():
    global _model, _model_key
    s = settings()
    key = ("fw", s.whisper_model, s.whisper_device, s.whisper_compute_type)
    with _lock:
        if _model is None or _model_key != key:
            from faster_whisper import WhisperModel
            opts = dict(device=s.whisper_device, compute_type=s.whisper_compute_type,
                        cpu_threads=max(1, (os.cpu_count() or 4) - 2))
            try:  # caché local primero: sin consultas a Hugging Face en cada arranque
                _model = WhisperModel(s.whisper_model, local_files_only=True, **opts)
            except Exception:  # primera vez: se descarga
                _model = WhisperModel(s.whisper_model, **opts)
            _model_key = key
        return _model


def transcribe(wav: Path, language: str | None = None,
               progress: Callable[[float], None] | None = None) -> tuple[list[dict], str]:
    """Devuelve (palabras, idioma). Tiempos relativos al archivo."""
    if settings().whisper_engine == "whisperx":
        try:
            return _transcribe_whisperx(wav, language)
        except ImportError:
            log.warning("WHISPER_ENGINE=whisperx pero whisperx no está instalado; uso faster-whisper")
    model = _faster_whisper()
    segments, info = model.transcribe(str(wav), language=language or None, word_timestamps=True,
                                      vad_filter=True, beam_size=5, condition_on_previous_text=False)
    tokens: list[dict] = []
    total = float(getattr(info, "duration", 0) or 0)
    for seg in segments:
        for w in seg.words or []:
            if (w.word or "").strip():
                # Sin limpiar: el espacio delante marca dónde empieza una palabra.
                tokens.append({"w": w.word, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
        if progress and total > 0:
            progress(min(1.0, float(seg.end) / total))
    return merge_continuations(tokens), (info.language or language or "es")


def _transcribe_whisperx(wav: Path, language: str | None) -> tuple[list[dict], str]:
    import whisperx  # opcional
    s = settings()
    model = whisperx.load_model(s.whisper_model, s.whisper_device, compute_type=s.whisper_compute_type,
                                language=language)
    audio = whisperx.load_audio(str(wav))
    result = model.transcribe(audio, batch_size=16)
    lang = result.get("language") or language or "es"
    align_model, meta = whisperx.load_align_model(language_code=lang, device=s.whisper_device)
    aligned = whisperx.align(result["segments"], align_model, meta, audio, s.whisper_device)
    words = [{"w": w["word"].strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
             for seg in aligned["segments"] for w in seg.get("words", [])
             if w.get("word", "").strip() and "start" in w and "end" in w]
    return words, lang
