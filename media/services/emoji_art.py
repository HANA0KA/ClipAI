"""Emojis a color como imágenes PNG para superponer en el render.

libass dibuja los emojis en blanco y negro (probado con libass 0.17 y Apple
Color Emoji: la silueta sale gris), así que no van dentro del `.ass`: se
dibujan con Pillow usando la fuente de emojis del sistema y se superponen con
el filtro `overlay` de ffmpeg.

Fuentes que se prueban, en orden: Apple Color Emoji (macOS), Noto Color Emoji
(Linux), Segoe UI Emoji (Windows). Cada PNG se valida (debe tener color); si
ninguna fuente sirve, `available()` es False y el render sigue sin emojis.
Caché en data/cache/emoji/.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path

from media.config import settings

log = logging.getLogger(__name__)

# (ruta, tamaño nativo del mapa de bits). Las fuentes de emojis a color traen
# mapas de bits fijos: pedir otro tamaño falla, así que se dibuja al nativo y
# se reescala.
_FONTS = (
    ("/System/Library/Fonts/Apple Color Emoji.ttc", 160),
    ("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109),
    ("/usr/share/fonts/noto/NotoColorEmoji.ttf", 109),
    ("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf", 109),
    ("C:/Windows/Fonts/seguiemj.ttf", 109),
)
_PROBE = "🔥"
_lock = threading.Lock()


def _cache_dir() -> Path:
    d = settings().cache_dir / "emoji"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _drawn(img) -> bool:
    """Hay un glifo (no un cuadro vacío)."""
    import numpy as np
    return img is not None and int((np.asarray(img.convert("RGBA"))[..., 3] > 32).sum()) >= 50


def _has_color(img) -> bool:
    """Para validar la FUENTE con un emoji muy colorido (🔥): una fuente que
    dibuja en gris no sirve. Emojis sueltos pueden ser grises (💻, 🎮)."""
    import numpy as np
    if not _drawn(img):
        return False
    arr = np.asarray(img.convert("RGBA"), dtype=np.int16)
    alpha = arr[..., 3] > 32
    rgb = arr[..., :3][alpha]
    spread = rgb.max(axis=1) - rgb.min(axis=1)
    return float((spread > 40).mean()) > 0.15


def _draw(char: str, font_path: str, native: int):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, native)
    canvas = Image.new("RGBA", (native * 2, native * 2), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((native // 2, native // 2), char, font=font, embedded_color=True)
    box = canvas.getbbox()
    return canvas.crop(box) if box else None


@lru_cache(maxsize=1)
def _font() -> tuple[str, int] | None:
    for path, native in _FONTS:
        if not Path(path).exists():
            continue
        try:
            img = _draw(_PROBE, path, native)
            if img is not None and _has_color(img):
                return path, native
            log.info("la fuente de emojis %s no dibuja a color; se prueba otra", path)
        except Exception as exc:  # fuente dañada o Pillow sin soporte de color
            log.info("fuente de emojis %s no disponible: %s", path, exc)
    return None


def available() -> bool:
    """¿Hay una fuente de emojis a color utilizable en este equipo?"""
    try:
        return _font() is not None
    except Exception:
        return False


def emoji_png(char: str, size: int) -> Path | None:
    """PNG cuadrado ``size``×``size`` con el emoji centrado; None si no se puede."""
    char = (char or "").replace("\ufe0f", "").strip()
    font = _font()
    if not char or font is None or size < 8:
        return None
    name = "-".join(f"{ord(c):x}" for c in char) + f"-{size}.png"
    out = _cache_dir() / name
    if out.exists():
        return out
    with _lock:
        if out.exists():
            return out
        try:
            from PIL import Image
            img = _draw(char, *font)
            if not _drawn(img):
                return None
            w, h = img.size
            scale = size / max(w, h)
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            square.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
            tmp = out.with_name(out.name + ".tmp.png")
            square.save(tmp, "PNG")
            tmp.replace(out)
            return out
        except Exception as exc:
            log.warning("no se pudo dibujar el emoji %r: %s", char, exc)
            return None


__all__ = ["available", "emoji_png"]
