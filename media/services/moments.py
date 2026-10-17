"""Prompts, esquemas y utilidades del detector de momentos."""
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


# Tipos de gancho (clave interna → etiqueta en español para la interfaz).
HOOK_TYPES = {
    "question": "pregunta",
    "statement": "afirmación",
    "statistic": "estadística",
    "story": "historia",
    "contrast": "contraste",
}
_HOOK_TYPE_ALIASES = {
    **{k: k for k in HOOK_TYPES},
    **{_v: k for k, _v in HOOK_TYPES.items()},
    "afirmacion": "statement", "estadistica": "statistic", "dato": "statistic",
    "claim": "statement", "stat": "statistic", "anecdote": "story", "anécdota": "story",
    "anecdota": "story", "comparison": "contrast", "comparación": "contrast",
}


def normalize_hook_type(value) -> str | None:
    """Acepta el tipo en inglés o en español; None si no es reconocible."""
    key = str(value or "").strip().lower()
    return _HOOK_TYPE_ALIASES.get(key)


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
    hook_type: str | None = None
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

    @field_validator("hook_type", mode="before")
    @classmethod
    def _hook_type(cls, v):
        return normalize_hook_type(v)

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

Propón hasta {n} momentos autocontenidos de {lo:.0f} a {hi:.0f} segundos que funcionen solos
como Short: un gancho fuerte al principio, una idea completa y un remate (conclusión, chiste,
revelación, lección o emoción fuerte). Empieza y termina en bordes de frase.
- LA DURACIÓN LA DECIDE LA HISTORIA: lo justo para que el gancho tenga sentido y la idea llegue
  a su remate ({hi:.0f} s como máximo). Si se cuenta en 70 s, 70 s; si necesita 2 minutos, 2
  minutos. No alargues ni rellenes para llegar a una duración.
- PRUEBA DE LOS 2 SEGUNDOS: los primeros 2 segundos deben frenar a alguien que no conoce
  el video. Si no lo hacen, empieza en la frase más fuerte.
- SE ENTIENDE SOLO: si arrancaría con un pronombre, un «eso», un «entonces» o la respuesta
  a algo preguntado antes, adelanta el inicio hasta donde empieza la idea. Arréglalo
  moviendo el INICIO, nunca cortando el remate.
- VARIEDAD: nunca dos momentos que cuenten lo mismo, la misma historia o el mismo chiste.
{query}
Devuelve solo JSON: una lista de objetos {{"start": segundos, "end": segundos, "reason": "por qué funciona"}}.

TRANSCRIPCIÓN:
{transcript}
"""

JUDGE_PROMPT = """Eres editor de Shorts y TikTok. Tienes la transcripción completa como contexto
y una lista de candidatos con id, inicio, fin y texto.
Califica cada candidato de 0 a 10 en:
- hook: PRUEBA DE LOS 2 SEGUNDOS: ¿los primeros 2 s frenan a alguien que no conoce el
  video? (pregunta, afirmación sorprendente, emoción fuerte, promesa clara). 0-3 si
  arranca a mitad de una idea.
- story: ¿se entiende sin ver el video completo y tiene remate (conclusión,
  chiste, revelación, lección)? 0-3 si termina cortado o si abre con un pronombre,
  un «eso», un «entonces» o la respuesta a algo preguntado antes. Resta también si se
  alarga sin aportar (relleno, repeticiones, desvíos): cada segundo debe sumar.
- value: ¿es útil, sorprendente, emotivo o identificable?
- engagement: ¿invita a comentar, discutir, guardar o compartir?
- reach: ¿lo entiende alguien que no conoce al creador ni el tema?
CALIBRA: usa toda la escala. La mayoría de los tramos de un video normal no son
clips: reserva 7 o más para los que pasan la prueba de los 2 segundos y deja relleno,
saludos, despedidas y transiciones en 3 o menos aunque el tema sea interesante.
VARIEDAD: si dos candidatos cuentan lo mismo (la misma idea, historia o chiste), puntúa
bajo el más flojo.
Puedes mover inicio y fin hasta 10 s para empezar en la frase más fuerte
y cerrar en el remate (usa los segundos de la transcripción). El clip dura lo que su
historia necesita, entre {lo:.0f} y {hi:.0f} segundos: ni más para rellenar ni menos si
el remate queda fuera. Si al candidato le falta contexto, adelanta el
INICIO hasta donde empieza la idea; nunca cortes el remate para ganar contexto. Cita
literalmente la frase más fuerte en best_line y explica en reason (1 frase) por qué funciona.
Propón un gancho en pantalla (hook_text): 3 a 8 palabras que se leen en un segundo y
obligan a quedarse. Elige la fórmula que encaje con ESTE clip: curiosidad (abre una
pregunta que el clip responde), contradicción (choca con lo que el público cree), lo que
está en juego o el error, un número o dato concreto del clip, o en segunda persona («tú»).
Nada genérico («Esto te sorprenderá», «No vas a creer», «Mira esto»), no reveles el remate
(el gancho abre la pregunta y el clip la cierra), no repitas la primera frase que se oye y
no prometas lo que el clip no cumple; sin hashtags ni comillas. Termina hook_text con UN emoji
del tema al final (p. ej. «¡Le trajo un conejo vivo de regalo! 🐰»): el gancho es a la vez el
título, la descripción y el texto de la portada.
DE ESTE MOMENTO, NO DEL VIDEO: el gancho y el título nombran lo concreto que pasa en
este clip (la acción, el número, la afirmación, el nombre). Una frase que serviría para
cualquier clip del video está mal; si no hay nada concreto, usa la frase más fuerte.
Clasifica cómo arranca el clip en hook_type: "question" (abre con una pregunta),
"statement" (afirmación audaz o sorprendente), "statistic" (un número o dato),
"story" (anécdota o relato), "contrast" (antes/después, problema/solución, "no es X, es Y").
Escribe también 3-5 hashtags (hashtags) en el idioma del video ({language}).
{query}
Responde solo JSON: una lista con un objeto por candidato con las claves
id, start, end, hook, story, value, engagement, reach, best_line, reason, hook_text,
hook_type, hashtags.

TRANSCRIPCIÓN:
{transcript}

CANDIDATOS (id|inicio-fin|texto):
{candidates}
"""


def build_propose_prompt(sents, duration, n, lo, hi, query, max_chars) -> str:
    return PROPOSE_PROMPT.format(duration=fmt_ts(duration), n=n, lo=lo, hi=hi,
                                 query=_query_block(query),
                                 transcript=transcript_for_prompt(sents, max_chars))


def _clip_text(text: str, limit: int) -> str:
    """Texto de un candidato dentro de ``limit`` caracteres: principio y
    final (lo que decide gancho y remate) si no cabe entero."""
    if len(text) <= limit:
        return text
    head = text[:int(limit * 0.6)].rsplit(" ", 1)[0]
    tail = text[-int(limit * 0.35):].split(" ", 1)[-1]
    return f"{head} … {tail}"


NO_CONTEXT = "(no disponible: juzga cada candidato solo con su propio texto)"


def build_judge_prompt(sents, candidates, language, query, max_chars, lo=60.0, hi=70.0,
                       context: bool = True) -> str:
    """``context=False`` omite la transcripción completa: se usa cuando el
    proveedor bloqueó el pedido con ella (a veces por una parte del video que
    no es ningún candidato)."""
    per = max(600, int(max_chars * 0.55) // max(1, len(candidates)))  # modelos con poco contexto
    cand_lines = "\n".join(f'{i}|{c["start"]:.1f}-{c["end"]:.1f}|{_clip_text(c["text"], per)}'
                           for i, c in enumerate(candidates))
    budget = max(4000, max_chars - len(cand_lines))
    return JUDGE_PROMPT.format(language=language or "es", query=_query_block(query), lo=lo, hi=hi,
                               transcript=transcript_for_prompt(sents, budget) if context else NO_CONTEXT,
                               candidates=cand_lines)


# ── Gancho en pantalla ───────────────────────────────────────────────────────

HOOK_MAX_WORDS = 10
HOOK_MAX_CHARS = 64
_QUOTES_RE = re.compile(r"[\"`“”‘«»„‚‹›]|(?<!\w)['’]|['’](?!\w)")  # conserva «don't»
_HOOK_TRIM = ".,;:-–—·/|"


def sanitize_hook(raw: str | None) -> str:
    """Titular gancho listo para usar.

    Quita comillas, hashtags, marcas de markdown y espacios de más; conserva
    ¿?¡! (son parte del gancho); corta a 10 palabras y a 64 caracteres, siempre
    en un espacio. Conserva UN emoji (el primero) al final: no cuenta como
    palabra. Devuelve "" si no queda nada útil. El video quema el gancho sin el
    emoji (`hook_plain`).
    """
    from media.services.emoji_text import split
    plain, emoji = split(str(raw or ""))
    text = _sanitize_plain(plain, reserve=len(emoji) + 1 if emoji else 0)
    return f"{text} {emoji}" if text and emoji else text


def hook_plain(raw: str | None) -> str:
    """El gancho como se quema en el video: limpio y sin emoji."""
    from media.services.emoji_text import strip_emoji
    return strip_emoji(sanitize_hook(raw))


def _sanitize_plain(raw: str, reserve: int = 0) -> str:
    text = str(raw or "")
    text = re.sub(r"#[\w\-áéíóúñü]+", " ", text, flags=re.IGNORECASE)
    text = text.replace("*", " ").replace("_", " ").replace("\n", " ")
    text = _QUOTES_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().strip(_HOOK_TRIM + " ")
    if not text:
        return ""
    words = text.split()
    if len(words) > HOOK_MAX_WORDS:
        text = " ".join(words[:HOOK_MAX_WORDS])
    limit = HOOK_MAX_CHARS - reserve
    if len(text) > limit:
        clipped = text[:limit + 1]
        cut = clipped.rfind(" ")
        text = clipped[:cut] if cut >= 20 else text[:limit]
    text = text.strip().rstrip(_HOOK_TRIM + " ").strip()
    # Signos de apertura sin cierre (el recorte se comió el final): se quitan.
    if "¿" in text and "?" not in text:
        text = text.replace("¿", "").strip()
    if "¡" in text and "!" not in text:
        text = text.replace("¡", "").strip()
    return text


# ── Calidad del gancho en pantalla ───────────────────────────────────────────

# Frases que sirven para cualquier video: el espectador ya las ignora.
GENERIC_HOOKS = (
    "esto te sorprendera", "no vas a creer", "no creeras", "mira esto", "mira lo que", "increible",
    "escucha esto", "tienes que ver", "no te lo pierdas", "atento a esto", "lo que paso", "mira hasta el final",
    "espera al final", "quedate hasta el final", "impactante", "wow", "you won't believe", "watch this",
    "wait for it", "this is crazy", "must watch",
)
_SECOND_PERSON = {"tu", "tus", "te", "ti", "contigo", "usted", "you", "your"}
HOOK_BEST_WORDS = (3, 8)


def _tokens(text: str) -> list[str]:
    return [t for t in (_norm(x) for x in str(text or "").split()) if t]


def hook_issues(hook: str, first_line: str = "") -> list[str]:
    """Defectos claros de un gancho en pantalla (lista vacía = sin defectos):
    vacío, genérico, demasiado corto o largo, o repite lo primero que se oye."""
    clean = sanitize_hook(hook)
    toks = _tokens(clean)
    issues = []
    if not toks:
        return ["vacío"]
    folded = " ".join(toks)
    if any(g.replace("'", "") in folded for g in GENERIC_HOOKS):
        issues.append("genérico")
    if len(toks) < HOOK_BEST_WORDS[0]:
        issues.append("corto")
    if len(toks) > HOOK_MAX_WORDS:
        issues.append("largo")
    spoken = set(_tokens(first_line))
    if spoken and len(set(toks) & spoken) / len(set(toks)) >= 0.8:
        issues.append("repite la primera frase")
    return issues


def hook_score(hook: str, first_line: str = "") -> float:
    """Puntuación 0–10 de un gancho en pantalla: sin defectos, en 3–8
    palabras y con algo concreto (número, palabra fuerte, «tú») puntúa alto."""
    from media.services import caption_fx

    issues = hook_issues(hook, first_line)
    if "vacío" in issues:
        return 0.0
    toks = _tokens(sanitize_hook(hook))
    score = 6.0 - 3.0 * len(issues)
    lo, hi = HOOK_BEST_WORDS
    score += 1.0 if lo <= len(toks) <= hi else -1.0
    if any(caption_fx.is_emphasis(caption_fx.normalize_token(t)) for t in toks):
        score += 1.5  # número o palabra fuerte
    if any(t in _SECOND_PERSON for t in toks):
        score += 1.0  # le habla al espectador
    if "?" in hook:
        score += 0.5
    return max(0.0, min(10.0, score))


def pick_hook(chosen: str, options: list[str] | tuple = (), first_line: str = "") -> tuple[str, list[str]]:
    """(gancho, alternativas): se queda con el que eligió la IA salvo que tenga
    defectos claros y otra opción no; entonces gana la mejor puntuada. Las
    alternativas sin defectos (limpias, sin repetir) se guardan para elegir en
    el estudio."""
    seen, pool = set(), []
    for raw in (chosen, *options):
        clean = sanitize_hook(raw)
        key = " ".join(_tokens(clean))
        if clean and key not in seen:
            seen.add(key)
            pool.append(clean)
    if not pool:
        return "", []
    best = pool[0]
    if hook_issues(best, first_line):
        best = max(pool, key=lambda h: (not hook_issues(h, first_line), hook_score(h, first_line)))
    return best, [h for h in pool if h != best and not hook_issues(h, first_line)][:3]


_STORY_RE = re.compile(
    r"\b(una vez|cuando (yo )?(era|tenía|estaba|empecé|fui)|me pasó|recuerdo|hace (unos )?(años|meses)|"
    r"el día que|mi (primer|primera)|i remember|one day|when i was|years ago|the day i|my first)\b",
    re.IGNORECASE)
_CONTRAST_RE = re.compile(
    r"\b(pero en realidad|en cambio|antes .{0,40} ahora|no es .{0,30} es|mientras que|la diferencia|"
    r"mito|versus|vs\.?|in reality|instead|used to .{0,40} now|not .{0,30} but|the difference)\b",
    re.IGNORECASE)
_STAT_RE = re.compile(
    r"\d|%|\b(mil|millón|millones|billón|por ciento|doble|triple|mitad|"
    r"thousand|million|billion|percent|half|twice)\b", re.IGNORECASE)


def classify_hook(text: str) -> str:
    """Tipo de gancho por reglas (respaldo sin IA) sobre la primera frase."""
    t = (text or "").strip()
    if not t:
        return "statement"
    if "?" in t or "¿" in t:
        return "question"
    if _CONTRAST_RE.search(t):
        return "contrast"
    if _STORY_RE.search(t):
        return "story"
    if _STAT_RE.search(t):
        return "statistic"
    return "statement"


# ── Frase más fuerte ─────────────────────────────────────────────────────────

def _norm(tok: str) -> str:
    tok = unicodedata.normalize("NFKD", tok.lower())
    return re.sub(r"[^\w]", "", "".join(c for c in tok if not unicodedata.combining(c)))


def locate_phrase(words: list[dict], phrase: str, start: float, end: float,
                  near: float | None = None) -> tuple[float, float] | None:
    """Ubica una cita (aproximada) dentro de [start, end] → (inicio, fin).
    Si la cita aparece varias veces, gana la primera; con ``near`` (el segundo
    que dio el modelo), la más cercana a él entre las que coinciden igual de bien."""
    target = [t for t in (_norm(x) for x in (phrase or "").split()) if t]
    ws = [w for w in words if start - 1 <= w["start"] < end + 1]
    toks = [_norm(w["w"]) for w in ws]
    if len(target) < 2 or len(ws) < 2:
        return None
    n = len(target)
    scores = [(SequenceMatcher(None, toks[k:k + n], target).ratio(), k)
              for k in range(0, max(1, len(toks) - n + 1))]
    best = max(r for r, _ in scores)
    if best < 0.6:
        return None
    ties = [k for r, k in scores if r >= best - 0.05] if near is not None else [k for r, k in scores if r == best]
    best_k = min(ties, key=lambda k: abs((ws[k]["start"] + ws[min(k + n, len(ws)) - 1]["end"]) / 2 - near)) \
        if near is not None else ties[0]
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
    from media.services import emoji_text
    hook_type = classify_hook(texts[0])
    # El gancho (con su emoji) es el título, la descripción y el texto de la portada.
    hook_full = emoji_text.ensure(hook or _shorten(texts[0], 60), hook_type, texts[0])
    return {
        "title": hook_full,
        "description": "",
        "hashtags": " ".join(dict.fromkeys(tags)),
        "hook": hook_full,
        "hook_type": hook_type,
        "reason": "Elegido por señales objetivas (sin IA): energía de audio, densidad, gancho textual"
                  " y heatmap si existe.",
    }
