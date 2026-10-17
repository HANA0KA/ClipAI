"""Hashtags sugeridos por red social (TikTok, Instagram, YouTube Shorts).

Cada red los usa distinto, así que cada una tiene su juego:

* TikTok: 3–5. Uno amplio de la comunidad del tema y el resto de nicho;
  TikTok clasifica por el contenido y los hashtags afinan a quién mostrarlo.
* Instagram (Reels): 3–5 de nicho y comunidad. Instagram admite como
  máximo 5 por publicación.
* YouTube Shorts: #Shorts primero y 2–3 del tema. YouTube muestra los
  tres primeros sobre el título e ignora todos si hay más de 15.

Etiquetas del canal (`apply_niche`): el creador del video original (su
canal de YouTube, p. ej. #LuisitoComunica) va delante y las fijas de tu
canal (HASHTAGS_BASE, p. ej. #YoutubersEspañoles #Streamers) al final, sin
pasar el tope de cada red y dejando siempre al menos 2 del tema del clip.

Todos se normalizan: una sola palabra (sin espacios ni signos), sin emojis,
sin duplicados (sin distinguir mayúsculas ni tildes) y sin etiquetas de
relleno que no aportan (#viral, #foryoupage repetidos, etc.). Con IA salen
del contenido concreto del clip; sin IA, de sus palabras más propias frente
al resto del video.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from pydantic import BaseModel, field_validator

from media.services import texttiling_ops

PLATFORMS = ("tiktok", "instagram", "youtube")
LIMITS = {"tiktok": (3, 5), "instagram": (3, 5), "youtube": (2, 3)}  # sin contar #Shorts
DISCOVERY = {  # una etiqueta amplia de descubrimiento por red e idioma
    "es": {"tiktok": "#parati", "instagram": "#reels"},
    "en": {"tiktok": "#fyp", "instagram": "#reels"},
}
# Etiquetas que no dicen nada del contenido (y que las redes tratan como ruido).
FILLER = {"viral", "viralvideo", "trending", "tendencia", "fy", "xyzbca", "explorepage", "like", "likes",
          "follow", "follow4follow", "f4f", "instagood", "shorts", "short", "youtubeshorts", "tiktok",
          "video", "videos"}
CAPS = {"tiktok": 6, "instagram": 5, "youtube": 5}  # con las del canal, sin contar #Shorts
MIN_TOPICS = 2
# Sufijos de nombres de canal que no son parte del nombre del creador.
_CHANNEL_SUFFIX = re.compile(r"(\s*-\s*topic|\s+vevo|vevo|\s+(oficial|official|tv))$", re.IGNORECASE)
# Etiquetas de «descubrimiento»: como mucho una por publicación, en TikTok e Instagram.
DISCOVERY_KEYS = {"fyp", "parati", "foryou", "foryoupage", "reels", "reel", "explore", "viralreels"}
_STOP = {"ahora", "cosa", "cosas", "gente", "vez", "hacer", "tiene", "tener", "puede", "creo", "digo",
         "dice", "quiero", "sabes", "mira", "vamos", "estaba", "porque", "entonces", "también", "tambien",
         "really", "thing", "things", "people", "going", "know", "like", "just", "think", "because"}


class HashtagSets(BaseModel):
    tiktok: list[str] = []
    instagram: list[str] = []
    youtube: list[str] = []

    @field_validator("tiktok", "instagram", "youtube", mode="before")
    @classmethod
    def _list(cls, v):
        if isinstance(v, str):
            v = v.replace(",", " ").split()
        return [str(x) for x in v or []]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def normalize_tag(raw: str) -> str | None:
    """«# Inteligencia artificial» → «#InteligenciaArtificial». None si no sirve."""
    text = str(raw or "").strip().lstrip("#").strip()
    parts = [p for p in re.split(r"[^\w]+", text, flags=re.UNICODE) if p]
    if not parts:
        return None
    tag = parts[0] if len(parts) == 1 else "".join(p[:1].upper() + p[1:] for p in parts)
    tag = tag.replace("_", "")
    if not tag or len(tag) > 30 or tag.isdigit():
        return None
    return "#" + tag


def clean_set(tags: list[str], platform: str, language: str | None = None) -> list[str]:
    """Normaliza, quita relleno y duplicados y aplica el límite de la red."""
    lo, hi = LIMITS[platform]
    out, seen, discovered = [], set(), False
    for raw in tags or []:
        tag = normalize_tag(raw)
        if not tag:
            continue
        key = _fold(tag[1:])
        if key in FILLER or key in seen:
            continue
        if key in DISCOVERY_KEYS:
            if discovered or platform == "youtube":
                continue
            discovered = True
        seen.add(key)
        out.append(tag)
    out = out[:hi]
    if platform == "youtube":
        out = ["#Shorts"] + out
    return out


def clean_sets(sets: dict | HashtagSets, language: str | None = None) -> dict:
    data = sets.model_dump() if isinstance(sets, HashtagSets) else dict(sets or {})
    return {p: clean_set(data.get(p) or [], p, language) for p in PLATFORMS}


def heuristic_sets(text: str, all_counts: Counter | None, language: str | None) -> dict:
    """Sin IA: las palabras más propias del clip frente al video entero."""
    toks = [t for t in texttiling_ops.tokenize(text) if len(t) > 4 and t not in _STOP]
    counts = Counter(toks)
    if all_counts:
        counts = Counter({t: c / (1 + all_counts.get(t, 0) ** 0.5) for t, c in counts.items()})
    keywords = [f"#{t}" for t, _ in counts.most_common(6)]
    disc = DISCOVERY.get((language or "es")[:2], DISCOVERY["es"])
    return clean_sets({
        "tiktok": [disc["tiktok"], *keywords[:4]],
        "instagram": [*keywords[:4], disc["instagram"]],
        "youtube": keywords[:3],
    }, language)


def complete(sets: dict, fallback: dict) -> dict:
    """Rellena con el respaldo la red que la IA dejó vacía o con menos del mínimo."""
    out = {}
    for p in PLATFORMS:
        mine = list(sets.get(p) or [])
        lo, _hi = LIMITS[p]
        body = [t for t in mine if t != "#Shorts"]
        if len(body) < lo:
            extra = [t for t in (fallback.get(p) or []) if t != "#Shorts" and _fold(t) not in {_fold(x) for x in body}]
            body = (body + extra)[:LIMITS[p][1]]
        out[p] = (["#Shorts"] if p == "youtube" else []) + body
    return out


def creator_tag(info: dict | None) -> str | None:
    """Hashtag del creador del video original a partir del info.json de
    yt-dlp: «Luisito Comunica» → #LuisitoComunica. None si no se sabe."""
    info = info or {}
    for key in ("channel", "uploader", "uploader_id"):
        name = str(info.get(key) or "").strip().lstrip("@")
        name = _CHANNEL_SUFFIX.sub("", name).strip()
        tag = normalize_tag(name) if name else None
        if tag:
            return tag
    return None


def base_tags(raw: str) -> list[str]:
    """HASHTAGS_BASE («#YoutubersEspañoles #Streamers», separadas por espacio
    o coma) → etiquetas normalizadas. «0», «no» o «-» las desactiva."""
    if (raw or "").strip().lower() in ("0", "no", "none", "-", "ninguno", "ninguna"):
        return []
    out, seen = [], set()
    for part in re.split(r"[,\s]+", raw or ""):
        tag = normalize_tag(part)
        if tag and _fold(tag[1:]) not in seen:
            seen.add(_fold(tag[1:]))
            out.append(tag)
    return out


def _pins(tags, seen: set[str]) -> list[str]:
    """Normaliza y quita repetidas (``seen`` acumula las claves ya usadas)."""
    out = []
    for raw in tags or ():
        tag = normalize_tag(raw)
        if tag and _fold(tag[1:]) not in seen:
            seen.add(_fold(tag[1:]))
            out.append(tag)
    return out


def apply_niche(sets: dict, lead: list[str] | tuple = (), tail: list[str] | tuple = (), prefer: str = "") -> dict:
    """Juegos finales por red: ``lead`` (el creador) delante, los del tema en
    medio y ``tail`` (las fijas del canal) al final. Respeta el tope de cada
    red (CAPS) dejando al menos MIN_TOPICS del tema; si no cabe todo, se
    recortan primero las fijas del final. Entre los del tema van primero los
    que salen en ``prefer`` (el título del video original: quién habla), para
    que el tope no los deje fuera. Idempotente."""
    seen: set[str] = set()
    lead, tail = _pins(lead, seen), _pins(tail, seen)
    if not seen:
        return {p: list(sets.get(p) or []) for p in PLATFORMS}
    title = _fold(re.sub(r"[\W_]+", "", prefer or ""))
    out = {}
    for p in PLATFORMS:
        topics = [t for t in sets.get(p) or [] if t != "#Shorts" and _fold(t.lstrip("#")) not in seen]
        if title:  # orden estable: solo suben los que nombran a alguien del título
            topics.sort(key=lambda t: not (len(_fold(t[1:])) >= 4 and _fold(t[1:]) in title))
        topics = topics[:max(min(MIN_TOPICS, len(topics)), CAPS[p] - len(lead) - len(tail))]
        room = CAPS[p] - len(topics)
        mine_lead = lead[:room]
        mine_tail = tail[:max(0, room - len(mine_lead))]
        out[p] = (["#Shorts"] if p == "youtube" else []) + mine_lead + topics + mine_tail
    return out


def apply_niche_line(line: str, lead: list[str] | tuple = (), tail: list[str] | tuple = (), cap: int = 8) -> str:
    """Lo mismo para el campo «Hashtags» del kit («#a #b #c»): creador,
    hasta ``cap`` en total con al menos MIN_TOPICS del tema, fijas al final."""
    seen: set[str] = set()
    lead, tail = _pins(lead, seen), _pins(tail, seen)
    topics = _pins(re.split(r"[,\s]+", line or ""), seen)
    if lead or tail:
        topics = topics[:max(MIN_TOPICS, cap - len(lead) - len(tail))]
    return " ".join(lead + topics + tail)


NETWORK_CAPS = {"youtube": 15, "instagram": 5}  # sin contar #Shorts; espejo de NETWORK_TAG_CAP en web/lib/network-tags.ts


def compose_network(platform: str, clip_set: list[str] | tuple = (), pinned: list[str] | tuple = ()) -> list[str]:
    """Juego final de YouTube o Instagram para un clip: las fijas que tú editas (valen para todos los videos)
    primero, luego las del clip, sin repetidas y hasta el tope de la red (#Shorts delante en YouTube).
    Debe coincidir con ``composeNetwork`` de web/lib/network-tags.ts."""
    seen: set[str] = {"shorts"} if platform == "youtube" else set()
    body = (_pins(pinned, seen) + _pins(clip_set, seen))[:NETWORK_CAPS[platform]]
    return (["#Shorts"] if platform == "youtube" else []) + body


PROMPT = """Eres estratega de redes sociales. Sugiere hashtags para publicar ESTE clip corto en
TikTok, Instagram Reels y YouTube Shorts, en el idioma del video ({language}).

Reglas:
- Sobre el contenido concreto del clip (tema, personas, conceptos, comunidad a la que le sirve),
  no genéricos de relleno (nada de #viral, #trending ni etiquetas engañosas o prohibidas).
- Una palabra o frase pegada cada uno (CamelCase si ayuda a leer), sin emojis.
- Si en el clip aparece o se nombra a alguien conocido (invitado, famoso, otro creador),
  uno lleva su nombre como se le conoce (p. ej. #Ibai) y va primero. El canal del video y las etiquetas
  generales de youtubers se añaden aparte: no las repitas.
- tiktok: 3 a 5 (1 amplio de la comunidad del tema + 2 a 4 de nicho).
- instagram: 3 a 5 de nicho y de comunidad (Instagram admite como máximo 5).
- youtube: 2 o 3 del tema (#Shorts se añade aparte).

VIDEO ORIGINAL: {video}
TÍTULO DEL CLIP: {title}
GANCHO: {hook}
LO QUE SE DICE EN EL CLIP:
{text}

Responde solo JSON: una lista con UN objeto con las claves tiktok, instagram, youtube.
"""


def build_prompt(text: str, title: str, hook: str, language: str | None, video: str = "") -> str:
    """``video``: título y canal del original (dice quién habla)."""
    words = text.split()
    if len(words) > 700:
        text = " ".join(words[:700]) + " …"
    return PROMPT.format(language=language or "es", title=title or "-", hook=hook or "-", text=text,
                         video=video.strip() or "-")


def video_label(info: dict | None, fallback_title: str | None = None) -> str:
    """«Título del video · canal Nombre» a partir del info.json de yt-dlp."""
    info = info or {}
    title = str(info.get("title") or fallback_title or "").strip()
    channel = str(info.get("channel") or info.get("uploader") or "").strip()
    return " · ".join(x for x in (title, f"canal {channel}" if channel else "") if x)


__all__ = ["HashtagSets", "normalize_tag", "clean_set", "clean_sets", "heuristic_sets", "complete",
           "build_prompt", "video_label", "creator_tag", "base_tags", "apply_niche", "apply_niche_line", "compose_network", "PLATFORMS", "LIMITS",
           "CAPS"]
