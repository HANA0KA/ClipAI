"""Arco narrativo de cada clip: gancho → contexto mínimo → desarrollo → remate.

La duración no es un número fijo: la decide la historia. Una vez elegidos
los mejores momentos, la IA marca en la transcripción de su zona:

* el GANCHO con que arranca (y, si hace falta, la frase de contexto mínima
  que lo hace entendible, nunca más atrás),
* el REMATE donde la idea se resuelve: el clip termina justo ahí,
* si conviene una APERTURA EN FRÍO (un avance de 2–5 s de la frase más
  potente) porque el inicio natural es flojo,
* el titular del gancho en pantalla y los hashtags por red.

La duración resultante queda entre CLIP_MIN_SEC y CLIP_MAX_SEC (máximo
absoluto 150 s) sin rellenar: si la historia se cuenta en 1:20 dura 1:20.
Las citas se ubican en las palabras reales (locate_phrase) y los segundos
del modelo solo se usan de respaldo; todo borde cae en frase o palabra.

Sin IA, `heuristic_end` busca el cierre natural: el primer final de frase
tras el mínimo seguido de un cambio de tema o de una pausa larga.
"""
from __future__ import annotations

import re
from bisect import bisect_left

from pydantic import BaseModel, field_validator

from media.services.moments import _to_seconds, locate_phrase, normalize_hook_type

CONTEXT_BEFORE = 25.0     # segundos de transcripción antes del clip que ve la IA
CONTEXT_AFTER = 15.0      # y después del máximo posible
MAX_START_SHIFT = 30.0    # el gancho no puede alejarse más que esto del candidato
TEASER_MIN, TEASER_MAX = 1.5, 6.0
CLOSURE_PAUSE = 1.0       # pausa que cuenta como cierre natural (sin IA)


class ArcPlan(BaseModel):
    id: int
    hook_quote: str = ""
    hook_start: float | None = None
    context: str = ""
    payoff_quote: str = ""
    payoff_end: float | None = None
    cold_open: bool = False
    teaser_quote: str = ""
    hook_text: str = ""
    hook_options: list[str] = []
    hook_type: str | None = None
    reason: str = ""
    tiktok: list[str] = []
    instagram: list[str] = []
    youtube: list[str] = []

    @field_validator("hook_start", "payoff_end", mode="before")
    @classmethod
    def _secs(cls, v):
        if v in (None, ""):
            return None
        try:
            return _to_seconds(v)
        except (TypeError, ValueError):
            return None

    @field_validator("hook_type", mode="before")
    @classmethod
    def _hook_type(cls, v):
        return normalize_hook_type(v)

    @field_validator("hook_options", mode="before")
    @classmethod
    def _options(cls, v):
        if isinstance(v, str):
            v = re.split(r"\s*[|\n]\s*", v)
        return [str(x).strip() for x in v or [] if str(x).strip()][:4]

    @field_validator("tiktok", "instagram", "youtube", mode="before")
    @classmethod
    def _tags(cls, v):
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        return [str(x).strip() for x in v or [] if str(x).strip()]


ARC_PROMPT = """Eres editor jefe de YouTube Shorts, Instagram Reels y TikTok. Para cada clip elegido
tienes la transcripción de su zona (el segundo de inicio de cada frase entre corchetes) y sus
bordes actuales. Define la ESTRUCTURA de cada clip:

1. GANCHO: la frase con la que arranca el clip. hook_quote = cita literal de esa frase y
   hook_start = su segundo de inicio. Tiene que frenar en 2 segundos a alguien que no conoce el
   video. Si el gancho necesita UNA frase previa para entenderse, empieza en esa frase (contexto
   mínimo), nunca antes. Nunca arranques con un pronombre, un «eso», un «entonces» o la respuesta
   a algo preguntado antes.
2. CONTEXTO: en una línea, qué necesita saber el espectador para que el gancho tenga sentido.
3. DESARROLLO: lo que sostiene la promesa del gancho, sin rodeos.
4. REMATE: la frase donde la idea se resuelve (conclusión, revelación, lección, chiste).
   payoff_quote = cita literal de esa frase y payoff_end = segundo en que termina. El clip
   termina justo ahí.

DURACIÓN: la decide la historia, entre {lo:.0f} y {hi:.0f} segundos ({hi:.0f} s es el máximo
absoluto). NO rellenes: si la historia se cuenta en 75 s, que dure 75 s; si necesita 130 s para
tener sentido, 130 s. Si la historia completa pasa de {hi:.0f} s, elige el arco completo más corto
que cumpla la promesa del gancho dentro de ese máximo. Cada segundo debe aportar: fuera saludos,
repeticiones y desvíos. Prioriza retención y claridad antes que cualquier duración.
Los clips no deben compartir tramo ni remate entre sí: si dos cuentan lo mismo, ajusta el
más flojo a su propia idea.

APERTURA EN FRÍO: cold_open = true solo si la frase más potente está a mitad del clip y el
arranque natural es flojo; entonces teaser_quote es esa frase (2 a 5 s, cita literal) y se
mostrará primero como avance. Si el gancho ya es fuerte, cold_open = false.

GANCHO EN PANTALLA: hook_text = 3 a 8 palabras que se leen en un segundo y obligan a quedarse,
y que prometen lo que el remate cumple. Elige la fórmula que encaje con ESTE clip: curiosidad
(abre una pregunta que el clip responde), contradicción (choca con lo que el público cree), lo
que está en juego o el error, un número o dato concreto del clip, o en segunda persona («tú»).
Usa lo concreto del clip (el nombre, el número, la acción). Nada genérico («Esto te
sorprenderá», «No vas a creer», «Mira esto»), no reveles el remate, no repitas la primera
frase que se oye; sin hashtags ni comillas. Termina hook_text con UN emoji del tema (p. ej.
«¡Le trajo un conejo vivo de regalo! 🐰»): el gancho es a la vez el título del post, su
descripción y el texto de la portada. hook_options: otras 2 versiones con fórmulas distintas
a la de hook_text, también con su emoji al final.
hook_type: "question", "statement", "statistic", "story" o "contrast".

HASHTAGS por red, en el idioma del video ({language}): una palabra o frase pegada cada uno
(CamelCase si ayuda a leer), sin emojis, sobre el contenido concreto de ESTE clip, nada de
relleno ni etiquetas prohibidas o engañosas. Si en el clip aparece o se nombra a alguien
conocido (invitado, famoso, otro creador), uno lleva su nombre como se le conoce (p. ej. #Ibai)
y va primero. El canal del video y las etiquetas generales de youtubers se añaden aparte: no las
repitas.
- tiktok: 3 a 5 (1 amplio de la comunidad del tema + 2 a 4 de nicho).
- instagram: 3 a 5 de nicho y de comunidad (Instagram admite como máximo 5).
- youtube: 2 o 3 del tema (#Shorts se añade aparte).

reason: una frase sobre por qué la estructura funciona.

Responde solo JSON: una lista con un objeto por clip con las claves id, hook_quote, hook_start,
context, payoff_quote, payoff_end, cold_open, teaser_quote, hook_text, hook_options, hook_type,
reason, tiktok, instagram, youtube.

VIDEO ORIGINAL: {video}

CLIPS:
{clips}
"""


def context_window(start: float, lo: float, hi: float, duration: float) -> tuple[float, float]:
    """Zona de transcripción que ve la IA para decidir el arco de un clip."""
    a = max(0.0, start - CONTEXT_BEFORE)
    b = min(duration, start + hi + CONTEXT_AFTER) if duration > 0 else start + hi + CONTEXT_AFTER
    return a, max(b, a + lo)


def build_arc_prompt(clips: list[dict], sents: list[dict], language: str, lo: float, hi: float,
                     duration: float, max_chars: int = 600_000, video: str = "") -> str:
    """``clips``: [{"start", "end"}] en el orden de sus ids. ``video``: título
    y canal del original (dice quién habla, para los hashtags de personas)."""
    blocks = []
    budget = max(2000, int(max_chars * 0.85) // max(1, len(clips)))
    for i, c in enumerate(clips):
        a, b = context_window(c["start"], lo, hi, duration)
        lines = [f"[{s['start']:.1f}] {s['text']}" for s in sents if s["end"] > a and s["start"] < b]
        text = "\n".join(lines)
        if len(text) > budget:  # modelos locales con poco contexto
            text = text[:budget].rsplit("\n", 1)[0]
        blocks.append(f"### id {i} · bordes actuales {c['start']:.1f}–{c['end']:.1f} s "
                      f"({c['end'] - c['start']:.0f} s)\n{text}")
    return ARC_PROMPT.format(lo=lo, hi=hi, language=language or "es", video=video.strip() or "-",
                             clips="\n\n".join(blocks))


# ── Resolución a bordes reales ───────────────────────────────────────────────

def _nearest_sentence_start(sents: list[dict], t: float) -> float | None:
    if not sents:
        return None
    return min((s["start"] for s in sents), key=lambda x: abs(x - t))


def _nearest_sentence_end(sents: list[dict], t: float) -> float | None:
    if not sents:
        return None
    return min((s["end"] for s in sents), key=lambda x: abs(x - t))


def resolve_arc(plan: ArcPlan, cand: dict, words: list[dict], sents: list[dict], *, lo: float, hi: float,
                duration: float) -> dict | None:
    """Bordes del arco en segundos del video: {"start", "end", "hook_end",
    "teaser"}. None si el plan no es utilizable (el llamador conserva los
    bordes del candidato). Las citas mandan; los segundos son respaldo."""
    a, b = context_window(cand["start"], lo, hi, duration)
    zone = [s for s in sents if s["end"] > a and s["start"] < b]
    start = None
    hook_end = None
    if plan.hook_quote:
        hit = locate_phrase(words, plan.hook_quote, a, b, near=plan.hook_start)
        if hit:
            start, hook_end = hit
    if start is None and plan.hook_start is not None and a - 1 <= plan.hook_start <= b:
        start = _nearest_sentence_start(zone, plan.hook_start)
    if start is None or abs(start - cand["start"]) > MAX_START_SHIFT:
        return None
    end = None
    if plan.payoff_quote:
        hit = locate_phrase(words, plan.payoff_quote, start, min(b, start + hi + 5), near=plan.payoff_end)
        if hit:
            end = hit[1]
    if end is None and plan.payoff_end is not None and start < plan.payoff_end <= b:
        end = _nearest_sentence_end([s for s in zone if s["end"] > start], plan.payoff_end)
    if end is None or end <= start:
        return None
    length = end - start
    if length < lo * 0.5 or length > hi * 1.15:
        return None  # el modelo ignoró la duración: mejor los bordes del candidato
    teaser = None
    if plan.cold_open and plan.teaser_quote:
        hit = locate_phrase(words, plan.teaser_quote, start, end)
        if hit and hit[0] - start >= 3.0 and TEASER_MIN <= hit[1] - hit[0] <= TEASER_MAX:
            teaser = (round(hit[0], 3), round(hit[1], 3))
    return {"start": round(start, 3), "end": round(end, 3),
            "hook_end": round(hook_end, 3) if hook_end else None, "teaser": teaser}


def heuristic_end(start: float, sents: list[dict], cuts: list[int], *, lo: float, hi: float,
                  duration: float) -> float | None:
    """Sin IA: el primer final de frase después del mínimo que cierra la idea
    (la frase siguiente empieza otro tema, o hay una pausa de ≥ 1 s). None si
    no hay cierre claro antes del máximo."""
    cut_set = set(cuts)
    i0 = bisect_left([s["start"] for s in sents], start - 0.05)
    for j in range(i0, len(sents)):
        end = sents[j]["end"]
        length = end - start
        if length > hi:
            return None
        if length < lo:
            continue
        nxt = sents[j + 1] if j + 1 < len(sents) else None
        if nxt is None or (j + 1) in cut_set or nxt["start"] - end >= CLOSURE_PAUSE:
            return min(end, duration) if duration > 0 else end
    return None


def hashtag_sets(plan: ArcPlan) -> dict:
    return {"tiktok": plan.tiktok, "instagram": plan.instagram, "youtube": plan.youtube}


__all__ = ["ArcPlan", "build_arc_prompt", "resolve_arc", "heuristic_end", "context_window", "hashtag_sets",
           "ARC_PROMPT"]
