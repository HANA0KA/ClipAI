"""Fuentes de video que ClipAI sabe descargar: YouTube y Kick (VODs).

* ``parse(url)`` reconoce el sitio y de qué es el enlace (video, canal, clip…).
  Misma regla en ``web/lib/sources.ts`` (deben coincidir).
* ``key(...)`` es la clave de la fuente para las cachés (``yt-<id>`` o
  ``kick-<uuid>``; con tramo: ``kick-<uuid>-s<inicio>-e<fin>``, porque otro
  tramo es otro texto).
* ``info(url)``, ``kick_channel_vods(slug)`` y ``youtube_channel_videos(clave)``
  sirven a la pantalla de nuevo proyecto: comprueban que el video existe (Kick
  borra los VODs a los pocos días) y, con un canal, listan sus videos.
* ``apply_range`` recorta la ficha (``source.info.json``) a un tramo descargado.

Sin imports pesados a nivel de módulo (yt_dlp y urllib dentro de las funciones).
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

from media.services.source_cache import youtube_id

KICK_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
KICK_SLUG = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
KICK_RESERVED = {"video", "videos", "categories", "category", "search", "browse", "following", "dashboard",
                 "community-guidelines", "terms-of-service", "privacy-policy", "help", "api", "clips"}
KICK_API = "https://kick.com/api/v2/channels/{slug}/videos"
KICK_VIDEO_API = "https://kick.com/api/v1/video/{uuid}"
KICK_CHANNEL_API = "https://kick.com/api/v2/channels/{slug}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MIN_RANGE_SECONDS = 60.0

# Canales de YouTube: @handle, /channel/UC…, /c/nombre y /user/nombre (con o sin pestaña al final).
YT_HANDLE = re.compile(r"^@[A-Za-z0-9._-]{3,30}$")
YT_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
YT_LEGACY_NAME = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_TABS = ("videos", "streams")
YT_CACHE_SECONDS = 600
_yt_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class SourceError(RuntimeError):
    """No se pudo leer la fuente (mensaje en español para el usuario)."""


def youtube_channel_key(raw: str | None, allow_bare: bool = False) -> str | None:
    """Clave canónica de un canal de YouTube («@handle», «channel/UC…», «c/nombre» o «user/nombre») o None.
    Con ``allow_bare`` también se acepta el handle o el id sueltos (lo que se escribe en el panel de canales);
    ``parse`` no lo permite: un texto sin sitio no es un enlace. Misma regla en ``web/lib/sources.ts``."""
    text = (raw or "").strip()
    if not text:
        return None
    if allow_bare and "/" not in text:
        bare = text if text.startswith("@") else ("@" + text if YT_HANDLE.match("@" + text) and not YT_CHANNEL_ID.match(text) else text)
        if YT_HANDLE.match(bare):
            return bare
        if YT_CHANNEL_ID.match(bare):
            return f"channel/{bare}"
    try:
        u = urlparse(text if "://" in text else "https://" + text)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if not (host == "youtube.com" or host.endswith(".youtube.com")):
        return None
    parts = [unquote(p) for p in u.path.split("/") if p]
    if not parts:
        return None
    if parts[0].startswith("@"):
        return parts[0] if YT_HANDLE.match(parts[0]) else None
    if len(parts) >= 2 and parts[0] == "channel":
        return f"channel/{parts[1]}" if YT_CHANNEL_ID.match(parts[1]) else None
    if len(parts) >= 2 and parts[0] in ("c", "user"):
        return f"{parts[0]}/{parts[1]}" if YT_LEGACY_NAME.match(parts[1]) else None
    return None


def parse(url: str | None) -> dict | None:
    """{"type": "youtube"|"kick", "kind": "video"|"channel"|"clip", "id", "channel"} o None si no es una fuente conocida.
    Un canal de YouTube lleva su clave (``youtube_channel_key``) en ``id`` y ``channel``."""
    text = (url or "").strip()
    if not text:
        return None
    try:
        u = urlparse(text if "://" in text else "https://" + text)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host == "kick.com" or host.endswith(".kick.com"):
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "videos" and KICK_UUID.match(parts[2]):
            return {"type": "kick", "kind": "video", "id": parts[2].lower(), "channel": parts[0]}
        if len(parts) == 2 and parts[0] == "video" and KICK_UUID.match(parts[1]):
            return {"type": "kick", "kind": "video", "id": parts[1].lower(), "channel": None}
        if parts and parts[0] not in KICK_RESERVED and KICK_SLUG.match(parts[0]):
            if (len(parts) >= 3 and parts[1] == "clips") or "clip" in parse_qs(u.query):
                return {"type": "kick", "kind": "clip", "id": None, "channel": parts[0]}
            if len(parts) == 1 or parts[1] in ("videos", "clips"):
                return {"type": "kick", "kind": "channel", "id": parts[0], "channel": parts[0]}
        return None
    vid = youtube_id(text)
    if vid:
        return {"type": "youtube", "kind": "video", "id": vid, "channel": None}
    ch = youtube_channel_key(text)
    if ch:
        return {"type": "youtube", "kind": "channel", "id": ch, "channel": ch}
    return None


def key(src: dict, start: float | None = None, end: float | None = None) -> str | None:
    """Clave de caché de la fuente (con su tramo, si se descarga solo una parte)."""
    if not src or src.get("kind") != "video" or not src.get("id"):
        return None
    base = ("yt-" if src["type"] == "youtube" else "kick-") + str(src["id"]).replace("-", "")[:32]
    if start is not None or end is not None:
        base += f"-s{int(start or 0)}-e{int(end or 0)}"
    return base


def check_range(start, end, max_minutes: float) -> tuple[float, float] | None:
    """(inicio, fin) válidos en segundos o None si no hay tramo. Lanza SourceError si es incoherente."""
    if start in (None, "") and end in (None, ""):
        return None
    try:
        a = float(start or 0)
        b = float(end)
    except (TypeError, ValueError) as exc:
        raise SourceError("El tramo necesita un inicio y un fin en segundos.") from exc
    if a < 0 or b <= a:
        raise SourceError("El fin del tramo debe quedar después del inicio.")
    if b - a < MIN_RANGE_SECONDS:
        raise SourceError(f"El tramo dura {b - a:.0f} s: elige al menos {MIN_RANGE_SECONDS:.0f} s (lo mínimo de un clip).")
    if b - a > max_minutes * 60:
        raise SourceError(f"El tramo dura {(b - a) / 60:.0f} min; el máximo es {max_minutes:.0f} min (MAX_VIDEO_MINUTES).")
    return a, b


def apply_range(info: dict, start: float, end: float) -> dict:
    """La ficha de un video del que solo se descargó [start, end]: la duración
    es la del tramo y capítulos y mapa de repeticiones (que cuentan desde el
    inicio del video) se corren para que sigan alineados con el archivo."""
    out = dict(info)
    out["full_duration"] = info.get("duration")
    out["duration"] = end - start
    out["range"] = {"start": start, "end": end}

    def shifted(items: list | None, s_key: str, e_key: str) -> list:
        res = []
        for it in items or []:
            a, b = float(it.get(s_key, 0)) - start, float(it.get(e_key, 0)) - start
            if b <= 0 or a >= end - start:
                continue
            res.append({**it, s_key: max(0.0, a), e_key: min(end - start, b)})
        return res

    out["chapters"] = shifted(info.get("chapters"), "start_time", "end_time")
    out["heatmap"] = shifted(info.get("heatmap"), "start_time", "end_time") or None
    return out


# ── Consultas a Kick ─────────────────────────────────────────────────────────

def _kick_json(url: str, what: str):
    """JSON de la API pública de Kick, con errores en español (404 → None)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SourceError(f"Kick no respondió ({exc.code}) al consultar {what}. Pega directamente el enlace del VOD.") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"No se pudo consultar {what} en Kick. Revisa tu conexión.") from exc


GONE = ("Este VOD ya no existe en Kick: Kick borra las transmisiones pasadas a los pocos días "
        "(pega el canal para ver los que siguen disponibles).")


def canonical_url(src: dict) -> str:
    """Enlace con el que yt-dlp reconoce un VOD de Kick: kick.com/<canal>/videos/<uuid>.
    Si el enlace no traía el canal (kick.com/video/<uuid>) se consulta a Kick."""
    if src["channel"]:
        return f"https://kick.com/{src['channel']}/videos/{src['id']}"
    data = _kick_json(KICK_VIDEO_API.format(uuid=src["id"]), "el VOD")
    if not isinstance(data, dict) or data.get("deleted_at") or data.get("is_pruned"):
        raise SourceError(GONE)
    slug = ((data.get("livestream") or {}).get("channel") or {}).get("slug")
    if not slug:
        raise SourceError("No se pudo saber de qué canal es ese VOD: pega el enlace con el canal (kick.com/canal/videos/…).")
    return f"https://kick.com/{slug}/videos/{src['id']}"


# ── Consultas para la pantalla de nuevo proyecto ─────────────────────────────

def _iso_date(ts) -> str | None:
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(float(ts))) if ts else None


def info(url: str, max_minutes: float) -> dict:
    """Ficha de un VOD de Kick (título, canal, duración…) o SourceError con el motivo."""
    src = parse(url)
    if not src or src["type"] != "kick" or src["kind"] != "video":
        raise SourceError("No es el enlace de un VOD de Kick (kick.com/canal/videos/…).")
    import yt_dlp
    url = canonical_url(src)
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 30}) as ydl:
            data = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "404" in msg or "not found" in msg.lower():
            raise SourceError(GONE) from exc
        raise SourceError(f"No se pudo leer el VOD de Kick: {msg[:200]}") from exc
    dur = float(data.get("duration") or 0)
    return {"type": "kick", "kind": "video", "id": src["id"], "title": data.get("title") or "",
            "channel": data.get("uploader") or data.get("channel") or src.get("channel") or "",
            "duration": dur, "uploadedAt": _iso_date(data.get("timestamp")), "views": data.get("view_count"),
            "thumbnail": data.get("thumbnail"), "live": bool(data.get("is_live")), "maxMinutes": max_minutes,
            "tooLong": dur / 60 > max_minutes}


def kick_profile(slug: str) -> dict | None:
    """Perfil público del canal (nombre, foto, seguidores, si está en directo);
    None si no se pudo leer: es un adorno, nunca impide listar los VODs."""
    try:
        data = _kick_json(KICK_CHANNEL_API.format(slug=slug), "el perfil")
    except SourceError:
        return None
    if not isinstance(data, dict):
        return None
    user = data.get("user") or {}
    live = data.get("livestream") or {}
    try:
        followers = int(data.get("followers_count") or data.get("followersCount") or 0) or None
    except (TypeError, ValueError):
        followers = None
    return {"name": user.get("username") or slug, "avatar": user.get("profile_pic"), "followers": followers,
            "verified": bool(data.get("verified")), "live": (live.get("session_title") or "En directo") if live else None}


def kick_channel_vods(slug: str, limit: int = 20) -> dict:
    """VODs recientes de un canal de Kick (la API pública del sitio) y su perfil."""
    data = _kick_json(KICK_API.format(slug=slug), f"el canal «{slug}»")
    if data is None:
        raise SourceError(f"No existe el canal «{slug}» en Kick.")
    vods = []
    for v in data if isinstance(data, list) else []:
        uuid = ((v.get("video") or {}).get("uuid") or "").lower()
        if not KICK_UUID.match(uuid):
            continue
        thumb = v.get("thumbnail")
        vods.append({
            "id": uuid, "url": f"https://kick.com/{slug}/videos/{uuid}", "title": v.get("session_title") or "",
            "createdAt": (v.get("created_at") or "")[:10] or None, "durationSec": round((v.get("duration") or 0) / 1000),
            "views": v.get("views"), "live": bool(v.get("is_live")),
            "thumbnail": thumb.get("src") if isinstance(thumb, dict) else thumb,
        })
        if len(vods) >= limit:
            break
    return {"channel": slug, "profile": kick_profile(slug), "vods": vods}


def _yt_profile(data: dict) -> dict:
    avatar = None
    for t in sorted(data.get("thumbnails") or [], key=lambda t: -(t.get("width") or 0)):
        if t.get("width") and t.get("width") == t.get("height"):  # la foto de perfil es la miniatura cuadrada
            avatar = t.get("url")
            break
    try:
        followers = int(data.get("channel_follower_count") or 0) or None
    except (TypeError, ValueError):
        followers = None
    return {"name": data.get("channel") or data.get("uploader") or data.get("title") or "", "avatar": avatar,
            "followers": followers, "verified": bool(data.get("channel_is_verified")),
            "handle": data.get("uploader_id") if str(data.get("uploader_id") or "").startswith("@") else None}


def youtube_channel_videos(key: str, tab: str = "videos", max_minutes: float = 240, limit: int = 24) -> dict:
    """Videos recientes de un canal de YouTube (listado plano de yt-dlp: sin descargar ficha por video, ~1 s).
    ``tab``: «videos» (subidos) o «streams» (directos ya terminados). Caché de 10 min."""
    import yt_dlp

    if tab not in YT_TABS:
        tab = "videos"
    ck = (key.lower(), tab)
    hit = _yt_cache.get(ck)
    if hit and time.time() - hit[0] < YT_CACHE_SECONDS:
        return hit[1]

    def fetch(which: str, n: int):
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
                "playlistend": n, "lazy_playlist": True, "socket_timeout": 30}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/{key}/{which}", download=False)

    try:
        data, missing_tab = fetch(tab, limit), False
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "does not have a" in msg and "tab" in msg and tab != "videos":
            missing_tab = True  # p. ej. un canal sin directos: se muestra vacío, con su perfil
            try:
                data = fetch("videos", 1)
            except yt_dlp.utils.DownloadError as exc2:
                raise SourceError(f"No se pudo leer el canal de YouTube: {str(exc2)[:200]}") from exc2
        elif "404" in msg or "Failed to resolve" in msg or "does not exist" in msg or "not found" in msg.lower():
            raise SourceError(f"No existe el canal «{key}» en YouTube.") from exc
        else:
            raise SourceError(f"No se pudo leer el canal de YouTube: {msg[:200]}") from exc
    videos = []
    for e in [] if missing_tab else list(data.get("entries") or []):
        vid = e.get("id") or ""
        if not YT_ID.match(vid):
            continue
        status = e.get("live_status")
        dur = float(e.get("duration") or 0)
        videos.append({
            "id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": e.get("title") or "",
            "durationSec": round(dur), "views": e.get("view_count"), "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            "live": status in ("is_live", "is_upcoming"), "tooLong": dur / 60 > max_minutes,
            "membersOnly": e.get("availability") in ("subscriber_only", "premium_only", "needs_auth"),
        })
    out = {"channel": key, "tab": tab, "profile": _yt_profile(data), "videos": videos, "maxMinutes": max_minutes,
           "missingTab": missing_tab}
    _yt_cache[ck] = (time.time(), out)
    return out


__all__ = ["SourceError", "parse", "youtube_channel_key", "youtube_channel_videos", "key", "check_range", "apply_range", "canonical_url", "info", "kick_profile", "kick_channel_vods"]
