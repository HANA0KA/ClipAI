"""Prompts, esquemas y utilidades del detector de momentos (plan 6.3)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from pydantic import BaseModel, field_validator

from media.services import texttiling_ops


def _to_seconds(v):
    if isinstance(v, str):
        v = v.strip()
        if ":" in v:
            parts = [float(p) for p in v.split(":")]
            secs = 0.0
            for p in parts:
                secs = secs * 60 + p
            return secs
        return float(v.rstrip("s"))
    return v


class Proposal(BaseModel):
    start: float
    end: float
    reason: str = ""

    @field_validator("start", "end", mode="before")
    @classmethod
    def _secs(cls, v):
        return _to_seconds(v)


def _clamp_axis(v):
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


class Judged(BaseModel):
    id: int
    start: float
    end: float
    hook: int
    story: int
    value: int
    engagement: int
    reach: int
    best_line: str = ""
    reason: str = ""
    hook_text: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = []

    @field_validator("start", "end", mode="before")
    @classmethod
    def _secs(cls, v):
        return _to_seconds(v)

    @field_validator("hook", "story", "value", "engagement", "reach", mode="before")
    @classmethod
    def _axes(cls, v):
        return _clamp_axis(v)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _tags(cls, v):
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        return [t if t.startswith("#") else f"#{t}" for t in (str(x).strip() for x in v or []) if t]


def fmt_ts(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def transcript_for_prompt(sents: list[dict], max_chars: int) -> str:
    """Una línea por frase con su segundo de inicio: `[123.4] texto`."""
    lines = [f"[{s['start']:.1f}] {s['text']}" for s in sents]
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    # Contexto limitado (modelo local): se muestrea uniformemente.
    keep = max(1, int(len(lines) * max_chars / len(text)))
    step = len(lines) / keep
    return "\n".join(lines[int(k * step)] for k in range(keep))


def _query_block(query: str | None) -> str:
    if not query:
        return ""
    return (f"\nCRITERIO DEL USUARIO (prioritario): busca momentos donde «{query}». "
            "Los candidatos que no cumplan este criterio deben puntuar bajo en value y reach.\n")


PROPOSE_PROMPT = """Eres editor de YouTube Shorts y TikTok. Abajo está la transcripción completa de un
video ({duration}) con el segundo de inicio de cada frase entre corchetes.

Propón hasta {n} momentos autocontenidos de {lo:.0f} a {hi:.0f} segundos que funcionen solos como
Short: un gancho fuerte al principio, una idea completa y un remate (conclusión, chiste,
revelación, lección o emoción fuerte). Empieza y termina en bordes de frase. No propongas
momentos que dependan de algo dicho antes.
{query}
Devuelve solo JSON: una lista de objetos {{"start": segundos, "end": segundos, "reason": "por qué funciona"}}.

TRANSCRIPCIÓN:
{transcript}
"""

JUDGE_PROMPT = """Eres editor de Shorts y TikTok. Tienes la transcripción completa como contexto
y una lista de candidatos con id, inicio, fin y texto.
Califica cada candidato de 0 a 10 en:
- hook: ¿los primeros 3 s frenan el scroll? (pregunta, afirmación sorprendente,
  emoción fuerte, promesa clara). 0-3 si arranca a mitad de una idea.
- story: ¿se entiende sin ver el video completo y tiene remate (conclusión,
  chiste, revelación, lección)? 0-3 si termina cortado.
- value: ¿es útil, sorprendente, emotivo o identificable?
- engagement: ¿invita a comentar, discutir, guardar o compartir?
- reach: ¿lo entiende alguien que no conoce al creador ni el tema?
Puedes mover inicio y fin hasta 10 s para empezar en la frase más fuerte
y cerrar en el remate (usa los segundos de la transcripción). Cita literalmente la
frase más fuerte en best_line y explica en reason (1 frase) por qué funciona.
Propón un gancho en pantalla (hook_text, máx. 8 palabras, que no repita la primera frase),
título para redes (title, máx. 100 caracteres, terminado en #Shorts), descripción de
2 líneas (description) y 3-5 hashtags en el idioma del video ({language}).
{query}
Responde solo JSON: una lista con un objeto por candidato con las claves
id, start, end, hook, story, value, engagement, reach, best_line, reason, hook_text,
title, description, hashtags.

TRANSCRIPCIÓN:
{transcript}

CANDIDATOS (id|inicio-fin|texto):
{candidates}
"""


def build_propose_prompt(sents, duration, n, lo, hi, query, max_chars) -> str:
    return PROPOSE_PROMPT.format(duration=fmt_ts(duration), n=n, lo=lo, hi=hi,
                                 query=_query_block(query),
                                 transcript=transcript_for_prompt(sents, max_chars))


def build_judge_prompt(sents, candidates, language, query, max_chars) -> str:
    cand_lines = "\n".join(f'{i}|{c["start"]:.1f}-{c["end"]:.1f}|{c["text"]}'
                           for i, c in enumerate(candidates))
    budget = max(4000, max_chars - len(cand_lines))
    return JUDGE_PROMPT.format(language=language or "es", query=_query_block(query),
                               transcript=transcript_for_prompt(sents, budget),
                               candidates=cand_lines)


# ── Frase más fuerte ─────────────────────────────────────────────────────────

def _norm(tok: str) -> str:
    tok = unicodedata.normalize("NFKD", tok.lower())
    return re.sub(r"[^\w]", "", "".join(c for c in tok if not unicodedata.combining(c)))


def locate_phrase(words: list[dict], phrase: str, start: float, end: float) -> tuple[float, float] | None:
    """Ubica una cita (aproximada) dentro de [start, end] → (inicio, fin)."""
    target = [t for t in (_norm(x) for x in (phrase or "").split()) if t]
    ws = [w for w in words if start - 1 <= w["start"] < end + 1]
    toks = [_norm(w["w"]) for w in ws]
    if len(target) < 2 or len(ws) < 2:
        return None
    n = len(target)
    best, best_k = 0.0, -1
    for k in range(0, max(1, len(toks) - n + 1)):
        r = SequenceMatcher(None, toks[k:k + n], target).ratio()
        if r > best:
            best, best_k = r, k
    if best < 0.6:
        return None
    seg = ws[best_k:best_k + n]
    return seg[0]["start"], seg[-1]["end"]


def prepend_span(words: list[dict], bl: tuple[float, float] | None, clip_start: float,
                 lo: float = 2.0, hi: float = 4.0) -> tuple[float, float] | None:
    """Tramo de 2–4 s de la frase más fuerte para anteponer (estilo OpusClip).
    Solo si la frase está a mitad del clip (no en los primeros 3 s)."""
    if bl is None or bl[0] - clip_start < 3.0:
        return None
    s = bl[0]
    ends = [w["end"] for w in words if s + lo <= w["end"] <= s + hi]
    e = ends[-1] if ends else min(bl[1], s + hi)
    return (round(s, 3), round(e, 3)) if e - s >= 1.5 else None


# ── Kit heurístico (sin IA) ──────────────────────────────────────────────────

_TAG_STOP = {"ahora", "cosa", "cosas", "gente", "vez", "hacer", "tiene", "tener", "puede",
             "creo", "digo", "dice", "quiero", "sabes", "mira", "vamos", "estaba", "really",
             "thing", "things", "people", "going", "know", "like", "just", "think"}


def _shorten(text: str, n_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n_chars:
        return text
    cut = text[:n_chars].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def heuristic_kit(clip_sents: list[dict], all_text_counts: Counter | None = None) -> dict:
    """Título, descripción, hashtags y gancho sin LLM, a partir del texto del clip."""
    texts = [s["text"] for s in clip_sents] or [""]
    # Frase gancho: la primera pregunta o frase con número; si no, la más larga del inicio.
    scored = sorted(texts[:6], key=lambda t: (("?" in t) * 2 + bool(re.search(r"\d", t)), len(t)),
                    reverse=True)
    lead = scored[0] if scored else texts[0]
    hook_words = lead.replace("¿", "").split()[:8]
    hook = " ".join(hook_words).rstrip(",.;:")
    toks = [t for t in texttiling_ops.tokenize(" ".join(texts)) if len(t) > 4 and t not in _TAG_STOP]
    counts = Counter(toks)
    if all_text_counts:
        # TF-IDF pobre: premia términos propios del clip frente al video entero.
        counts = Counter({t: c / (1 + all_text_counts.get(t, 0) ** 0.5) for t, c in counts.items()})
    tags = [f"#{t}" for t, _ in counts.most_common(4)] + ["#shorts"]
    return {
        "title": _shorten(texts[0], 88) + " #Shorts",
        "description": _shorten(" ".join(texts[:3]), 220),
        "hashtags": " ".join(dict.fromkeys(tags)),
        "hook": hook,
        "reason": "Elegido por señales objetivas (sin IA): energía de audio, densidad, gancho textual"
                  " y heatmap si existe.",
    }
