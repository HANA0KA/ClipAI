"""Caché por fuente: procesar otra vez el mismo video no gasta IA ni tiempo.

La clave es el id del video de YouTube (``yt-<id>``) o, para archivos
subidos, una huella del archivo (``up-<sha256 de tamaño + primeros y últimos
4 MB>``). En data/cache/sources/<clave>/ se guardan la transcripción, los
análisis (uno por combinación de parámetros) y el pulido con Whisper de cada
tramo. El video no se guarda aquí: si otro proyecto ya lo descargó, se enlaza
(hardlink) su source.mp4 en vez de volver a bajarlo.

Idea de SupoClip (`_build_cache_key` + tabla processing_cache); código propio.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from media.config import settings
from media.services.atomic import read_json, write_json

VERSION = 1  # cambiarlo invalida todos los análisis guardados
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
KEY_FILE = "cache_key.txt"


def youtube_id(url: str | None) -> str | None:
    """watch?v=, youtu.be/, /shorts/, /live/ y /embed/ → id de 11 caracteres."""
    if not url:
        return None
    try:
        u = urlparse(url.strip() if "://" in url else "https://" + url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    cand = None
    if host.endswith("youtu.be"):
        cand = u.path.strip("/").split("/")[0]
    elif "youtube.com" in host:
        if u.path == "/watch":
            cand = (parse_qs(u.query).get("v") or [None])[0]
        else:
            parts = [p for p in u.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
                cand = parts[1]
    return cand if cand and _ID_RE.match(cand) else None


def file_fingerprint(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as fh:
        h.update(fh.read(chunk))
        if size > chunk:
            fh.seek(max(chunk, size - chunk))
            h.update(fh.read(chunk))
    return h.hexdigest()[:24]


def project_key(project: dict, folder: Path) -> str | None:
    """Clave de la fuente del proyecto (None si no se puede saber aún)."""
    saved = folder / KEY_FILE
    if saved.exists():
        key = saved.read_text(encoding="utf-8").strip()
        if key:
            return key
    if project.get("sourceType") == "youtube":
        vid = youtube_id(project.get("sourceUrl"))
        return f"yt-{vid}" if vid else None
    return None


def remember_key(folder: Path, key: str) -> None:
    (folder / KEY_FILE).write_text(key, encoding="utf-8")


def _dir(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", key)[:80]
    return settings().cache_dir / "sources" / safe


def load(key: str | None, name: str):
    if not key:
        return None
    return read_json(_dir(key) / name)


def save(key: str | None, name: str, data) -> None:
    if not key:
        return
    d = _dir(key)
    d.mkdir(parents=True, exist_ok=True)
    write_json(d / name, data)


def signature(params: dict) -> str:
    raw = json.dumps({"v": VERSION, **params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink (no ocupa espacio extra y sobrevive si el otro proyecto se
    limpia o se borra); copia si están en discos distintos."""
    tmp = dst.with_name(dst.name + ".link.tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    tmp.replace(dst)


SOURCE_FILES = ("source.mp4", "audio.wav", "source.info.json")


def find_sibling_source(project: dict) -> Path | None:
    """Carpeta de otro proyecto con el mismo video de YouTube ya descargado."""
    from media.services import db
    vid = youtube_id(project.get("sourceUrl"))
    if not vid:
        return None
    root = settings().projects_dir
    for other in db.list_projects():
        if other["id"] == project["id"] or other.get("sourceType") != "youtube":
            continue
        if youtube_id(other.get("sourceUrl")) != vid:
            continue
        folder = root / other["id"]
        if all((folder / f).exists() for f in SOURCE_FILES):
            return folder
    return None


def reuse_source(sibling: Path, folder: Path) -> None:
    """Enlaza el video, el audio, el info.json y los subtítulos del hermano."""
    for name in SOURCE_FILES:
        link_or_copy(sibling / name, folder / name)
    for sub in sibling.glob("source.*"):
        if sub.suffix in (".json3", ".vtt") and not (folder / sub.name).exists():
            link_or_copy(sub, folder / sub.name)


__all__ = ["youtube_id", "file_fingerprint", "project_key", "remember_key", "load", "save", "signature",
           "find_sibling_source", "reuse_source", "link_or_copy"]
