"""Texto para PUBLICAR un clip: título, descripción y hashtags con el nombre del creador.

El gancho (``Clip.hook``) sigue siendo el texto de la portada, el del video y el nombre de los archivos:
aquí no se toca. Al publicar se le suma quién es el protagonista, porque así es como la gente busca en
YouTube: por el nombre del creador (título, primeras líneas de la descripción y hashtags).

* Título: «Creador: gancho» (si el gancho ya nombra al creador, se deja igual). Máximo 100 (YouTube).
* Descripción: 2–3 líneas: quién es, de qué video sale y el enlace al video completo.
* Hashtags: el del creador y el del formato (#Clips) delante, sin quitar los que ya tenías.

Puro y sin imports pesados. El nombre sale del ``source.info.json`` de yt-dlp (canal o autor).
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from media.services import hashtags

TITLE_MAX = 100


def _fold(text: str) -> str:
    """Sin tildes, mayúsculas ni signos: para saber si un texto ya nombra a alguien."""
    base = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    return "".join(c for c in base if c.isalnum())


def creator_name(info: dict | None) -> str | None:
    """«Luisito Comunica» del info.json (canal, autor o @usuario, sin sufijos como «- Topic» o «VEVO»)."""
    info = info or {}
    for key in ("channel", "uploader", "uploader_id"):
        name = str(info.get(key) or "").strip().lstrip("@")
        name = hashtags._CHANNEL_SUFFIX.sub("", name).strip()
        if name and hashtags.normalize_tag(name):
            return name[:60]
    return None


_cache: dict[tuple[str, float], str | None] = {}


def creator_for(folder: Path) -> str | None:
    """El creador de un proyecto; se lee una vez por archivo (el info.json pesa varios MB)."""
    path = Path(folder) / "source.info.json"
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key not in _cache:
        import json
        try:
            _cache[key] = creator_name(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            _cache[key] = None
        if len(_cache) > 64:
            _cache.pop(next(iter(_cache)))
    return _cache[key]


def post_title(hook: str, creator: str | None) -> str:
    hook = (hook or "").strip()
    if not creator or not hook or _fold(creator) in _fold(hook):
        return hook[:TITLE_MAX]
    full = f"{creator}: {hook}"
    return full if len(full) <= TITLE_MAX else hook[:TITLE_MAX]


def post_description(hook: str, creator: str | None, video_title: str | None = None, source_url: str | None = None) -> str:
    hook = (hook or "").strip()
    lines = []
    if hook:
        lines.append(f"Clip de {creator}: {hook}" if creator and _fold(creator) not in _fold(hook) else hook)
    vt = (video_title or "").strip()
    if vt:
        lines.append(f"Del video «{vt[:120]}»." if not vt.endswith(".") else f"Del video «{vt[:120]}»")
    url = (source_url or "").strip()
    if url.startswith(("http://", "https://")):
        lines.append(f"Video completo: {url}")
    return "\n".join(lines)


def post_hashtags(line: str, creator: str | None, fmt: str = "") -> str:
    """Los hashtags del clip con el del creador y el del formato delante (una sola vez, sin quitar ninguno)."""
    lead = [t for t in [hashtags.normalize_tag(creator) if creator else None, *hashtags.base_tags(fmt)] if t]
    seen = {hashtags._fold(t[1:]) for t in lead}
    rest = [t for t in (hashtags.normalize_tag(x) for x in (line or "").replace(",", " ").split())
            if t and hashtags._fold(t[1:]) not in seen]
    out, dup = [], set()
    for t in [*lead, *rest]:
        k = hashtags._fold(t[1:])
        if k not in dup:
            dup.add(k)
            out.append(t)
    return " ".join(out)


def network_pins(path: Path) -> dict[str, list[str]]:
    """Fijas por red que editas en la web (``data/network-hashtags.json``: {youtube, instagram}); vacío si no hay."""
    import json
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return {"youtube": [], "instagram": []}
    return {n: [t for t in (hashtags.normalize_tag(x) for x in (raw.get(n) or []) if isinstance(x, str)) if t]
            for n in ("youtube", "instagram")}


def build(hook: str, hashtags_line: str, *, creator: str | None, video_title: str | None, source_url: str | None,
          fmt: str = "") -> dict:
    return {"creator": creator, "title": post_title(hook, creator),
            "description": post_description(hook, creator, video_title, source_url),
            "hashtags": post_hashtags(hashtags_line, creator, fmt)}


__all__ = ["network_pins", "creator_name", "creator_for", "post_title", "post_description", "post_hashtags", "build"]
