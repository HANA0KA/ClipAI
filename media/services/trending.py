"""Tendencias: videos de YouTube con potencial para clips.

YouTube ya no publica una lista de «tendencias», así que se usa su buscador
con filtros (fecha, tipo, duración y orden por vistas: el parámetro ``sp``) y
después se puntúa cada candidato con lo que dice su ficha (fecha, vistas,
likes, comentarios, suscriptores del canal, capítulos y subtítulos). Todo
local y gratis: yt-dlp, sin claves ni IA.

Puntaje 0–100 (cada parte explica su razón en español):
  · Impulso (35): vistas por día desde que se subió (2 mil/día → 0; 2 M/día → 35).
  · Rendimiento (20): vistas frente a los suscriptores del canal (un video que
    se sale de su público habitual se comparte y se comenta).
  · Reacción (15): likes y comentarios sobre las vistas.
  · Material para clips (30): duración (mucho habla = varios clips), capítulos
    (ya vienen divididos por temas), subtítulos (análisis rápido) y formato de
    conversación (podcast, entrevista, debate…).

Sin imports pesados a nivel de módulo (yt_dlp se importa dentro de la función).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from media.config import settings
from media.services.atomic import read_json, write_json

log = logging.getLogger(__name__)

PERIODS = {"hour": 1, "day": 2, "week": 3, "month": 4, "year": 5}
SORTS = {"relevance": 0, "date": 2, "views": 3}
DURATIONS = {"short": 1, "long": 2, "medium": 3}  # <4 min, >20 min, 4–20 min
MIN_MINUTES = 5.0          # menos que esto no da para varios clips
RESULT_TTL = 30 * 60       # lista de resultados
VIDEO_TTL = 6 * 3600       # ficha de cada video
MAX_CANDIDATES = 60
CACHE_VERSION = 2          # súbelo cuando cambie qué lleva una ficha o su puntaje: invalida las cachés
TALK_RE = re.compile(r"\b(podcast|entrevista|debate|charla|conversaci[oó]n|episodio|ep\.?\s*\d+|#\s?\d+|"
                     r"reacci[oó]n|reacciona|historia|cuenta|confiesa|responde|interview|episode|reacts?|"
                     r"stream|directo|en vivo)\b", re.IGNORECASE)


class TrendingError(RuntimeError):
    """YouTube no respondió o rechazó la búsqueda."""


# ── Búsqueda ─────────────────────────────────────────────────────────────────

def search_filter(sort: str = "views", period: str | None = "week", duration: str | None = "long") -> str:
    """Valor del parámetro ``sp`` de la búsqueda de YouTube: orden, fecha,
    tipo (siempre video) y duración, en su formato protobuf en base64."""
    filt = bytearray()
    if period in PERIODS:
        filt += bytes([0x08, PERIODS[period]])
    filt += bytes([0x10, 1])  # tipo: video
    if duration in DURATIONS:
        filt += bytes([0x18, DURATIONS[duration]])
    msg = (bytes([0x08, SORTS[sort]]) if SORTS.get(sort) else b"") + bytes([0x12, len(filt)]) + bytes(filt)
    return quote(base64.urlsafe_b64encode(msg).decode(), safe="")


def search_url(query: str, sort: str, period: str | None, duration: str | None) -> str:
    return (f"https://www.youtube.com/results?search_query={quote(query.strip())}"
            f"&sp={search_filter(sort, period, duration)}")


def _ydl_opts(**extra) -> dict:
    return {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20,
            "noplaylist": True, **extra}


def search(query: str, sort: str, period: str | None, duration: str | None, count: int) -> list[dict]:
    """Primeros ``count`` resultados (fichas parciales: id, título, canal, vistas, duración)."""
    import yt_dlp
    opts = _ydl_opts(extract_flat="in_playlist", playlist_items=f"1:{count}")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url(query, sort, period, duration), download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise TrendingError(f"La búsqueda «{query}» falló: {str(exc)[:200]}") from exc
    return [e for e in (info or {}).get("entries") or [] if e and e.get("id")]


def details(video_id: str) -> dict | None:
    """Ficha completa (sin formatos: ~3 s en paralelo) o None si no se pudo leer."""
    import yt_dlp
    opts = _ydl_opts(extractor_args={"youtube": {"player_skip": ["configs"]}})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False, process=False)
    except Exception as exc:  # un video privado o bloqueado no tumba la lista
        log.info("ficha de %s no disponible: %s", video_id, str(exc)[:150])
        return None


def spoken_language(full: dict) -> str | None:
    """Idioma hablado («es», «pt»…): el que YouTube marca como original en los
    subtítulos automáticos (clave «es-orig») o, si no, el campo ``language``."""
    for key in full.get("automatic_captions") or {}:
        if key.endswith("-orig"):
            return key[:-5].split("-")[0].lower() or None
    lang = full.get("language")
    return str(lang).split("-")[0].lower() if lang else None


_LATIN_LANGS = {"es", "en", "pt", "fr", "it", "de", "ca", "nl", "ro", "pl", "tr", "id", "sv", "da", "no"}


def wrong_script(title: str, want: str | None) -> bool:
    """Un título casi todo en otro alfabeto (hindi, árabe, cirílico, chino…) no
    es de quien busca en un idioma de alfabeto latino. Sirve cuando el video
    no tiene subtítulos y su idioma no está confirmado."""
    if want not in _LATIN_LANGS:
        return False
    letters = [c for c in title if c.isalpha()]
    return len(letters) >= 4 and sum(1 for c in letters if ord(c) > 0x24F) / len(letters) > 0.25


def real_subtitles(full: dict) -> bool:
    """Subtítulos subidos por el creador (el chat de un directo no cuenta)."""
    return any(k != "live_chat" for k in full.get("subtitles") or {})


def normalize(flat: dict, full: dict | None) -> dict:
    """Ficha común a partir del resultado de búsqueda y (si hay) la ficha completa."""
    f = full or {}
    followers = f.get("channel_follower_count")
    return {
        "id": flat["id"],
        "title": (f.get("title") or flat.get("title") or "").strip(),
        "channel": f.get("channel") or f.get("uploader") or flat.get("channel") or flat.get("uploader") or "",
        "views": f.get("view_count") if f.get("view_count") is not None else flat.get("view_count"),
        "likes": f.get("like_count"),
        "comments": f.get("comment_count"),
        "timestamp": f.get("timestamp"),
        "duration": f.get("duration") or flat.get("duration"),
        "followers": followers if isinstance(followers, (int, float)) and followers >= 1000 else None,
        "chapters": len(f.get("chapters") or []),
        "subs_manual": real_subtitles(f),
        "language": spoken_language(f),
        "subs_auto": bool(f.get("automatic_captions")),
        "live_status": f.get("live_status") or flat.get("live_status"),
        "age_limit": f.get("age_limit") or 0,
        "availability": f.get("availability"),
        "partial": full is None,
    }


# ── Puntaje ──────────────────────────────────────────────────────────────────

def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def fmt_count(n: float) -> str:
    """3 200 000 → «3,2 M»; 845 000 → «845 mil»; 12 300 → «12 mil»; 950 → «950»."""
    n = float(n)
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " M" if v < 100 else f"{v:.0f} M"
    if n >= 10_000:
        return f"{round(n / 1000):.0f} mil"
    if n >= 1000:
        return f"{n / 1000:.1f}".replace(".", ",") + " mil"
    return f"{n:.0f}"


def fmt_span(days: float) -> str:
    if days < 1:
        return "menos de un día" if days >= 0.05 else "unas horas"
    d = round(days)
    return "1 día" if d == 1 else f"{d} días" if d < 60 else f"{round(d / 30)} meses"


def fmt_duration(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def tier(score: float) -> str:
    return "muy alto" if score >= 78 else "alto" if score >= 60 else "medio" if score >= 40 else "bajo"


def score(v: dict, now: float | None = None, max_minutes: float | None = None) -> dict:
    """{"score", "tier", "reasons", "warnings", "parts"} de una ficha normalizada."""
    now = time.time() if now is None else now
    max_minutes = settings().max_video_minutes if max_minutes is None else max_minutes
    reasons: list[str] = []
    warnings: list[str] = []
    views = v.get("views") or 0
    minutes = (v.get("duration") or 0) / 60

    # Impulso
    age_days = max(0.0, (now - v["timestamp"]) / 86400) if v.get("timestamp") else None
    if age_days is not None and views:
        per_day = views / max(age_days, 0.25)
        momentum = 35 * _clamp((math.log10(max(per_day, 1)) - 3.3) / (6.3 - 3.3))
        hot = "Explotando: " if per_day >= 500_000 else "Con mucho movimiento: " if per_day >= 60_000 else ""
        reasons.append(f"{hot}{fmt_count(views)} vistas en {fmt_span(age_days)} (≈ {fmt_count(per_day)} por día)")
    else:
        momentum = 12.0
        if views:
            reasons.append(f"{fmt_count(views)} vistas")
    # Rendimiento frente al canal
    if v.get("followers") and views:
        ratio = views / v["followers"]
        outperform = 20 * _clamp((math.log10(max(ratio, 1e-4)) + 1.3) / 1.3)
        if ratio >= 1:
            reasons.append(f"Tiene {ratio:.1f}".replace(".", ",") + "× más vistas que suscriptores: se salió de su público habitual")
        elif ratio >= 0.25:
            reasons.append(f"Alcanza el {ratio * 100:.0f} % de los suscriptores del canal")
    else:
        outperform = 8.0
    # Reacción
    if views and v.get("likes") is not None:
        like_rate = v["likes"] / views
        engagement = 10 * _clamp(like_rate / 0.05)
        if like_rate >= 0.04:
            reasons.append(f"Muy querido: {like_rate * 100:.1f} % de likes".replace(".", ","))
    else:
        engagement = 4.0
    if views and v.get("comments") is not None:
        c_rate = v["comments"] / views
        engagement += 5 * _clamp(c_rate / 0.003)
        if c_rate >= 0.002 and v["comments"] >= 500:
            reasons.append(f"Genera conversación: {fmt_count(v['comments'])} comentarios")
    else:
        engagement += 2.0
    # Material para clips
    if minutes > max_minutes:
        duration_pts = 0
        warnings.append(f"Dura {fmt_duration(v['duration'])}: supera el máximo de {max_minutes:.0f} min que ClipAI procesa")
    else:
        duration_pts = 13 if minutes >= 20 else 8 if minutes >= 10 else 4 if minutes >= MIN_MINUTES else 0
        if minutes >= 20:
            reasons.append(f"{fmt_duration(v['duration'])} de habla: material para varios clips")
        elif minutes >= MIN_MINUTES:
            reasons.append(f"{fmt_duration(v['duration'])}: alcanza para pocos clips")
    chapters = v.get("chapters") or 0
    chapter_pts = 9 if chapters >= 8 else 5 if chapters >= 3 else 0
    if chapters >= 3:
        reasons.append(f"{chapters} capítulos: ya viene dividido por temas")
    if v.get("subs_manual"):
        subs_pts = 5
        reasons.append("Subtítulos del creador: transcripción exacta y análisis rápido")
    elif v.get("subs_auto"):
        subs_pts = 4
        reasons.append("Subtítulos automáticos: análisis rápido")
    else:
        subs_pts = 0
        warnings.append("Sin subtítulos: se transcribirá con Whisper (tarda más)")
    talk_pts = 3 if TALK_RE.search(v.get("title") or "") else 0
    if talk_pts:
        reasons.append("Formato de conversación: frases completas y con remate")
    if v.get("live_status") == "was_live":
        reasons.append("Fue un directo: los momentos fuertes suelen ser largos y espontáneos")
    clip_pts = min(30, duration_pts + chapter_pts + subs_pts + talk_pts)

    total = round(momentum + outperform + engagement + clip_pts)
    if age_days is not None and age_days > 45:
        warnings.append("Ya no es reciente: la ola de vistas pudo pasar")
    return {"score": int(max(0, min(100, total))), "tier": tier(total), "reasons": reasons[:6],
            "warnings": warnings,
            "parts": {"momentum": round(momentum), "outperform": round(outperform),
                      "engagement": round(engagement), "clips": round(clip_pts)}}


def excluded(v: dict, max_minutes: float | None = None) -> str | None:
    """Motivo por el que ClipAI no puede o no vale la pena procesarlo (o None)."""
    max_minutes = settings().max_video_minutes if max_minutes is None else max_minutes
    if v.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        return "en directo"
    if not v.get("duration"):
        return "sin duración"
    if v["duration"] / 60 < MIN_MINUTES:
        return "muy corto"
    if v["duration"] / 60 > max_minutes:
        return "demasiado largo"
    if v.get("age_limit", 0) >= 18:
        return "solo adultos"
    if v.get("availability") not in (None, "public", "unlisted"):
        return "no es público"
    return None


# ── Descubrir ────────────────────────────────────────────────────────────────

def resolve_lang(lang: str | None) -> str | None:
    """«auto»/vacío → TRENDING_LANG; «any» → sin filtro; si no, el código dado («es», «en»…)."""
    lang = (lang or "auto").strip().lower()
    if lang == "auto":
        lang = settings().trending_lang.strip().lower()
    return None if lang in ("", "any") else lang.split("-")[0][:3]


def default_topics() -> list[str]:
    return [t.strip() for t in settings().trending_topics.split(",") if t.strip()]


def _cache_dir() -> Path:
    d = settings().cache_dir / "trending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fresh(path: Path, ttl: float) -> dict | None:
    data = read_json(path)
    if isinstance(data, dict) and time.time() - float(data.get("at", 0)) < ttl:
        return data
    return None


def _card(video_id: str, flat: dict, refresh: bool) -> dict:
    path = _cache_dir() / f"v{CACHE_VERSION}-{video_id}.json"
    cached = None if refresh else _fresh(path, VIDEO_TTL)
    if cached:
        return {**cached["card"], "views": flat.get("view_count") or cached["card"].get("views")}
    card = normalize(flat, details(video_id))
    if not card["partial"]:
        write_json(path, {"at": time.time(), "card": card})
    return card


def discover(query: str | None = None, *, period: str = "week", sort: str = "views", duration: str | None = "long",
             topics: list[str] | None = None, per_query: int | None = None, limit: int = 24, refresh: bool = False,
             lang: str | None = "auto") -> dict:
    """Videos con potencial para clips, del más al menos prometedor.

    ``query`` vacío: se buscan los temas (``topics`` o TRENDING_TOPICS) y se
    juntan. ``lang``: idioma hablado que quieres («auto» = TRENDING_LANG, «any» =
    todos; los de idioma desconocido se dejan). Devuelve {"items", "meta"};
    ``meta`` dice qué se buscó, cuántos se ocultaron (en directo, demasiado
    largos, otro idioma…) y si viene de la caché (30 min)."""
    want = resolve_lang(lang)
    queries = [query.strip()] if query and query.strip() else (topics or default_topics())
    if not queries:
        raise TrendingError("No hay temas que buscar: escribe una búsqueda o define TRENDING_TOPICS en .env.")
    per_query = per_query or (25 if len(queries) == 1 else 12)  # un tema solo necesita más donde elegir
    key = hashlib.sha1(json.dumps([CACHE_VERSION, queries, period, sort, duration, per_query, limit, want],
                                  ensure_ascii=False).encode()).hexdigest()[:20]
    cache = _cache_dir() / f"r-{key}.json"
    if not refresh:
        hit = _fresh(cache, RESULT_TTL)
        if hit:
            return {"items": hit["items"], "meta": {**hit["meta"], "cached": True}}

    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
        results = list(pool.map(lambda q: _safe_search(q, sort, period, duration, per_query), queries))
    if not any(ok for ok, _ in results):
        raise TrendingError(next((r for ok, r in results if not ok), "YouTube no devolvió resultados."))
    seen: dict[str, dict] = {}
    for (ok, entries), q in zip(results, queries):
        for rank, e in enumerate(entries if ok else []):
            item = seen.setdefault(e["id"], {**e, "_topics": [], "_rank": rank})
            item["_topics"].append(q)
    flats = sorted(seen.values(), key=lambda e: (e["_rank"], -(e.get("view_count") or 0)))[:MAX_CANDIDATES]

    with ThreadPoolExecutor(max_workers=8) as pool:
        cards = list(pool.map(lambda e: _card(e["id"], e, refresh), flats))
    now = time.time()
    items, hidden = [], {}
    for flat, card in zip(flats, cards):
        why = excluded(card)
        if not why and want and ((card.get("language") and card["language"] != want)
                                 or (not card.get("language") and wrong_script(card["title"], want))):
            why = "otro idioma"
        if why:
            hidden[why] = hidden.get(why, 0) + 1
            continue
        scored = score(card, now)
        items.append({
            "id": card["id"], "url": f"https://www.youtube.com/watch?v={card['id']}", "title": card["title"],
            "channel": card["channel"], "thumbnail": f"https://i.ytimg.com/vi/{card['id']}/hqdefault.jpg",
            "views": card["views"], "likes": card["likes"], "comments": card["comments"],
            "uploadedAt": time.strftime("%Y-%m-%d", time.gmtime(card["timestamp"])) if card["timestamp"] else None,
            "ageDays": round((now - card["timestamp"]) / 86400, 1) if card["timestamp"] else None,
            "durationSec": int(card["duration"]), "followers": card["followers"], "chapters": card["chapters"],
            "subtitles": "manual" if card["subs_manual"] else "auto" if card["subs_auto"] else None,
            "language": card.get("language"),
            "topics": flat["_topics"], "partial": card["partial"], **scored,
        })
    items.sort(key=lambda i: (-i["score"], -(i["views"] or 0)))
    meta = {"queries": queries, "period": period, "sort": sort, "duration": duration, "lang": want, "hidden": hidden,
            "found": len(flats), "cached": False, "at": int(now)}
    write_json(cache, {"at": now, "items": items[:limit], "meta": meta})
    return {"items": items[:limit], "meta": meta}


def _safe_search(q: str, sort: str, period: str, duration: str | None, count: int) -> tuple[bool, list[dict] | str]:
    try:
        return True, search(q, sort, period, duration, count)
    except TrendingError as exc:
        log.warning("%s", exc)
        return False, str(exc)


__all__ = ["TrendingError", "discover", "score", "excluded", "search_filter", "search_url", "normalize",
           "default_topics", "fmt_count", "tier", "resolve_lang", "spoken_language", "real_subtitles"]
