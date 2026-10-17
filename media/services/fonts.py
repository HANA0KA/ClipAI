"""Fuentes para libass: las incluidas (media/fonts) y las que subes (TTF/OTF).

libass solo mira UNA carpeta (`fontsdir`), así que el render usa data/fonts/:
ahí se enlazan las fuentes incluidas y se guardan las subidas con prefijo
``user-``. El nombre que va en el estilo ASS es la familia que declara el
propio archivo (tabla `name`), leída con Pillow.

Idea de SupoClip (`font_registry.py`); código propio.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from pathlib import Path

from media.config import FONTS_DIR, settings

log = logging.getLogger(__name__)

EXTENSIONS = (".ttf", ".otf")
MAX_BYTES = 15 * 1024 * 1024
USER_PREFIX = "user-"
_MAGIC = (b"\x00\x01\x00\x00", b"true", b"OTTO")
_lock = threading.Lock()
_names: dict[tuple[str, float, int], tuple[str, str]] = {}


class FontError(ValueError):
    pass


def _link_or_copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    tmp.replace(dst)


def fonts_dir() -> Path:
    """data/fonts con las fuentes incluidas al día (se enlazan, no se copian)."""
    d = settings().user_fonts_dir
    d.mkdir(parents=True, exist_ok=True)
    with _lock:
        for src in bundled_files():
            dst = d / src.name
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                _link_or_copy(src, dst)
    return d


def bundled_files() -> list[Path]:
    return sorted(p for p in FONTS_DIR.iterdir() if p.suffix.lower() in EXTENSIONS)


def family_of(path: Path) -> tuple[str, str]:
    """(familia, estilo) declarados en la fuente. Cacheado por archivo."""
    st = path.stat()
    key = (str(path), st.st_mtime, st.st_size)
    if key not in _names:
        from PIL import ImageFont
        family, style = ImageFont.truetype(str(path), 24).getname()
        _names[key] = ((family or "").strip(), (style or "").strip())
    return _names[key]


_PLAIN_STYLES = {"", "regular", "normal", "book", "roman", "bold", "italic", "bold italic", "oblique"}


def ass_name(family: str, style: str) -> str:
    """Nombre para el estilo ASS: la familia para estilos básicos y el nombre
    completo («Montserrat ExtraBold») para pesos intermedios, que libass
    también reconoce."""
    return family if style.strip().lower() in _PLAIN_STYLES else f"{family} {style}".strip()


def list_fonts() -> list[dict]:
    d = fonts_dir()
    bundled = {p.name for p in bundled_files()}
    out = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() not in EXTENSIONS or p.name.endswith(".tmp"):
            continue
        try:
            family, style = family_of(p)
        except Exception as exc:
            log.warning("fuente ilegible %s: %s", p.name, exc)
            continue
        out.append({"file": p.name, "family": family, "style": style, "name": ass_name(family, style),
                    "builtin": p.name in bundled})
    return out


def find_font_file(family: str) -> Path | None:
    """Archivo de una familia (para medir texto); None si no está. No escribe
    nada en disco: mira media/fonts y, si existe, data/fonts."""
    want = (family or "").strip().lower()
    if not want:
        return None
    user_dir = settings().user_fonts_dir
    user = sorted(p for p in user_dir.iterdir() if p.name.startswith(USER_PREFIX)
                  and p.suffix.lower() in EXTENSIONS) if user_dir.is_dir() else []
    for p in [*bundled_files(), *user]:
        try:
            fam, style = family_of(p)
        except Exception:
            continue
        if want in (fam.lower(), f"{fam} {style}".lower(), ass_name(fam, style).lower()):
            return p
    return None


def _safe_stem(name: str) -> str:
    stem = Path(name or "fuente").stem
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:60]
    return stem or "fuente"


def add_font(filename: str, data: bytes) -> dict:
    """Valida y guarda una fuente subida. Devuelve su entrada de `list_fonts`."""
    ext = Path(filename or "").suffix.lower()
    if ext not in EXTENSIONS:
        raise FontError("Sube una fuente .ttf u .otf.")
    if not data or len(data) < 1024:
        raise FontError("El archivo está vacío o incompleto.")
    if len(data) > MAX_BYTES:
        raise FontError("La fuente pesa más de 15 MB.")
    if data[:4] not in _MAGIC:
        raise FontError("El archivo no es una fuente TrueType u OpenType válida.")
    d = fonts_dir()
    dst = d / f"{USER_PREFIX}{_safe_stem(filename)}{ext}"
    tmp = d / f".{dst.name}.upload"
    tmp.write_bytes(data)
    try:
        family, style = family_of(tmp)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise FontError(f"No se pudo leer la fuente: {exc}") from exc
    if not family or len(family) > 80 or "," in family:
        tmp.unlink(missing_ok=True)
        raise FontError("La fuente no declara un nombre de familia utilizable.")
    tmp.replace(dst)
    return {"file": dst.name, "family": family, "style": style, "name": ass_name(family, style),
            "builtin": False}


def delete_font(file: str) -> None:
    name = Path(file or "").name
    if not name.startswith(USER_PREFIX) or Path(name).suffix.lower() not in EXTENSIONS:
        raise FontError("Solo se pueden borrar las fuentes que subiste.")
    path = settings().user_fonts_dir / name
    if not path.exists():
        raise FontError("La fuente no existe.")
    path.unlink()


__all__ = ["fonts_dir", "list_fonts", "find_font_file", "family_of", "ass_name", "add_font",
           "delete_font", "FontError", "EXTENSIONS"]
