"""Portada de cada clip: un cuadro del video con el gancho en grande.

* Cuadro: el que elijas en el estudio (segundo del video fuente) o, en
  automático, el mejor del clip (rostro + nitidez + exposición, la misma
  puntuación que la miniatura) sobre ``reframed.mp4``: el clip ya encuadrado
  y SIN subtítulos ni gancho quemados.
* Texto: el gancho (o el que escribas), limpio como el del video
  (`moments.sanitize_hook`), en 1–4 líneas equilibradas y lo más grande que
  quepa; números y palabras fuertes en el color de acento. El emoji del gancho
  («¡Le trajo un conejo vivo de regalo! 🐰») va a color y grande, centrado
  debajo del texto (libass no dibuja emojis a color: se superpone como imagen).
* Zona segura: TikTok e Instagram muestran la portada recortada a 3:4 en el
  perfil y TikTok tapa la franja de abajo con su interfaz; el texto queda
  siempre dentro (entre el 16 % y el 84 % del alto).
* Estilos: «contorno» (letra blanca con borde negro grueso, el de las
  miniaturas) o «caja» (la caja del gancho de la plantilla).
* Se dibuja con libass (mismas fuentes que el render) y con los filtros de
  color del estudio; detrás del texto el fondo se oscurece en una franja
  degradada (sin bordes) para que resalte sin apagar la imagen.

Ajustes en ``Clip.cover`` (JSON): ``{"text", "time", "position", "style",
"dim"}``; ``time`` en segundos del video fuente o None (automático).
"""
from __future__ import annotations

import json
import os
from itertools import combinations
from pathlib import Path

POSITIONS = ("top", "center", "bottom")
STYLES = ("outline", "box")
DEFAULTS = {"text": None, "time": None, "position": "center", "style": "outline", "dim": True}
MAX_TEXT = 120            # caracteres que se guardan (el limpiado deja ≤ 64)
SIDE = 80                 # margen lateral (base 1080)
SAFE_TOP, SAFE_BOTTOM = 0.16, 0.84  # zona segura vertical (fracción del alto)
SIZE_MAX, SIZE_MIN = 150, 70        # tamaño de letra (base 1080)
MAX_LINES = 4
LINE_HEIGHT = 1.18
SHRINK = 0.94
OUTLINE, SHADOW, BOX_PAD = 0.085, 0.045, 0.14  # en proporción al tamaño de letra
DIM_STRENGTH = 0.55   # cuánto se oscurece el centro de la franja detrás del texto
FILE = "cover.jpg"
_AUTO_CACHE = "cover.auto.json"
_ACCENT_STOP = {"porque", "cuando", "donde", "sobre", "entre", "desde", "hasta", "tiene", "hacer", "puede",
                "todos", "todas", "nadie", "nunca", "siempre", "about", "their", "there", "which", "would"}


class CoverError(RuntimeError):
    """No se puede hacer la portada (p. ej. el clip aún no tiene render)."""


# ── Ajustes ──────────────────────────────────────────────────────────────────

def parse(raw) -> dict:
    """JSON de la columna (o dict del estudio) → ajustes completos y válidos."""
    data: dict = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    out = dict(DEFAULTS)
    text = data.get("text")
    out["text"] = str(text).strip()[:MAX_TEXT] or None if text is not None else None
    try:
        t = data.get("time")
        out["time"] = round(float(t), 3) if t is not None and float(t) >= 0 else None
    except (TypeError, ValueError):
        out["time"] = None
    if data.get("position") in POSITIONS:
        out["position"] = data["position"]
    if data.get("style") in STYLES:
        out["style"] = data["style"]
    if isinstance(data.get("dim"), bool):
        out["dim"] = data["dim"]
    return out


def merge(current, patch: dict) -> dict:
    """Ajustes guardados + los que llegan (solo las claves presentes)."""
    base = parse(current)
    return parse({**base, **{k: v for k, v in (patch or {}).items() if k in DEFAULTS}})


def clip_offset(parts: list[tuple[float, float]], t: float | None) -> float | None:
    """Segundo del video fuente → segundo del clip montado (None si ese
    momento ya no está en el clip)."""
    if t is None:
        return None
    off = 0.0
    for a, b in parts:
        if a <= t < b:
            return off + (t - a)
        off += b - a
    return None


# ── Texto ────────────────────────────────────────────────────────────────────

def split_balanced(words: list[str], n: int, measure) -> list[str]:
    """``n`` líneas con la más larga lo más corta posible."""
    if n <= 1 or len(words) <= 1:
        return [" ".join(words)]
    n = min(n, len(words))
    best, best_key = None, None
    for cuts in combinations(range(1, len(words)), n - 1):
        bounds = (0, *cuts, len(words))
        lines = [" ".join(words[bounds[i]:bounds[i + 1]]) for i in range(n)]
        widths = [measure(x) for x in lines]
        key = (max(widths), max(widths) - min(widths))
        if best_key is None or key < best_key:
            best, best_key = lines, key
    return best


def fit_text(text: str, *, measure, max_width: float, max_height: float, size_max: float,
             size_min: float) -> tuple[list[str], float]:
    """(líneas, tamaño): la letra más grande con la que el texto cabe en
    ``max_lines`` líneas dentro del ancho y el alto dados. ``measure(texto,
    tamaño) → ancho``."""
    words = text.split()
    if not words:
        return [], size_max
    size = size_max
    while size >= size_min:
        for n in range(1, min(MAX_LINES, len(words)) + 1):
            lines = split_balanced(words, n, lambda t, s=size: measure(t, s))
            if max(measure(x, size) for x in lines) <= max_width and n * size * LINE_HEIGHT <= max_height:
                return lines, size
        size *= SHRINK
    lines = split_balanced(words, min(MAX_LINES, len(words)), lambda t: measure(t, size_min))
    longest = max(measure(x, size_min) for x in lines)
    return lines, size_min * min(1.0, max_width / longest) if longest else size_min


def accent_words(words: list[str]) -> set[int]:
    """Índices de las palabras en color de acento: números y palabras fuertes
    (como el gancho del video); si no hay ninguna, la palabra más larga, para
    que la portada tenga siempre un punto de color."""
    from media.services import caption_fx
    norm = [caption_fx.normalize_token(w) for w in words]
    hits = {i for i, t in enumerate(norm) if caption_fx.is_emphasis(t)}
    if hits or not words:
        return hits
    candidates = [(len(t), -i) for i, t in enumerate(norm) if len(t) >= 5 and t not in _ACCENT_STOP]
    return {-max(candidates)[1]} if candidates else set()


EMOJI_SCALE = 1.3    # tamaño del emoji respecto a la letra
EMOJI_GAP = 0.14     # separación entre el texto y el emoji (en tamaños de letra)


def build_ass(text: str, *, tpl: dict, width: int, height: int, position: str = "center",
              style: str = "outline", font: str | None = None) -> tuple[str, tuple[float, float] | None]:
    """(ASS de un solo evento con el texto de la portada, (centro y alto del
    bloque de texto)). ('', None) si no hay texto útil."""
    made = layout(text, tpl=tpl, width=width, height=height, position=position, style=style, font=font)
    return (made["ass"], made["band"]) if made else ("", None)


def layout(text: str, *, tpl: dict, width: int, height: int, position: str = "center",
           style: str = "outline", font: str | None = None, emoji: bool = False) -> dict | None:
    """{"ass", "band": (centro y alto del bloque incluido el emoji), "emoji":
    (x, y, tamaño) del centro del emoji o None}. None si no hay texto útil.
    ``emoji``: reserva sitio debajo del texto para el emoji del gancho."""
    from media.services import ass_builder as ab
    from media.services.emoji_text import strip_emoji
    from media.services.moments import sanitize_hook

    hook = tpl.get("hook", {})
    clean = strip_emoji(sanitize_hook(text))
    if not clean:
        return None
    if hook.get("uppercase", tpl.get("uppercase", True)):
        clean = clean.upper()
    fs, _vs = ab._scales(width, height)
    font = font or hook.get("font", tpl["font"])
    top, bottom = height * SAFE_TOP, height * SAFE_BOTTOM
    # El borde (contorno o caja) ocupa espacio a cada lado del texto.
    edge = BOX_PAD if style == "box" else OUTLINE
    max_width = width - 2 * SIDE * fs
    # Con emoji, el texto se ajusta a lo que queda encima de él.
    room = 0.0

    def fit(room_h: float):
        return fit_text(
            clean, measure=lambda t, s: ab.text_width(t, font, s) + 2 * edge * s,
            max_width=max_width, max_height=bottom - top - room_h, size_max=SIZE_MAX * fs, size_min=SIZE_MIN * fs)

    lines, size = fit(0.0)
    if emoji:
        for _ in range(3):  # el emoji mide como la letra; se reserva su alto y se reajusta
            room = size * (EMOJI_SCALE + EMOJI_GAP)
            lines, size = fit(room)
        room = size * (EMOJI_SCALE + EMOJI_GAP)
    words = clean.split()
    accents = accent_words(words)
    if style == "box":
        base_c, accent_c = hook.get("text", "#111111"), ab._hook_accent(tpl, hook)
    else:
        base_c, accent_c = "#FFFFFF", tpl.get("highlight", "#FFE600")
    base, accent = ab._inline(base_c), ab._inline(accent_c)
    rendered, k = [], 0
    for line in lines:
        parts = []
        for word in line.split():
            t = ab.escape_text(word)
            parts.append(f"{{\\c{accent}}}{t}{{\\c{base}}}" if k in accents and accent != base else t)
            k += 1
        rendered.append(" ".join(parts))
    x = width / 2
    # El grupo (texto + emoji debajo) se coloca como un solo bloque.
    anchor = {"top": (8, top), "center": (5, (top + bottom) / 2 - room / 2), "bottom": (2, bottom - room)}[position]
    block_h = len(lines) * size * LINE_HEIGHT
    text_center = {"top": top + block_h / 2, "center": anchor[1], "bottom": bottom - room - block_h / 2}[position]
    emoji_at = (x, text_center + block_h / 2 + size * EMOJI_GAP + size * EMOJI_SCALE / 2,
                round(size * EMOJI_SCALE)) if emoji else None
    center_y = text_center + room / 2
    block_h += room
    pos = f"\\an{anchor[0]}\\pos({ab._num(x)},{ab._num(anchor[1])})"
    hidden = ab.ass_color("#000000", 0xFF)
    size_i = round(size)
    tail = "5,0,0,0,1"
    if style == "box":
        alpha = max(0, min(255, int(hook.get("box_alpha", 0))))
        box = ab.ass_color(hook.get("box", "#FFE600"), alpha)
        pad = ab._num(BOX_PAD * size)
        text_c = ab.ass_color(base_c)
        if alpha:  # caja translúcida: caja y texto en capas aparte (como en el video)
            styles = [f"Style: Cover,{font},{size_i},{text_c},{text_c},{hidden},{hidden},-1,0,0,0,100,100,0,0,1,0,0,{tail}",
                      f"Style: CoverBox,{font},{size_i},{hidden},{hidden},{box},{hidden},-1,0,0,0,100,100,0,0,3,{pad},0,{tail}"]
        else:
            styles = [f"Style: Cover,{font},{size_i},{text_c},{text_c},{box},{hidden},-1,0,0,0,100,100,0,0,3,{pad},0,{tail}"]
    else:
        alpha = 0
        styles = [f"Style: Cover,{font},{size_i},{ab.ass_color('#FFFFFF')},{ab.ass_color('#FFFFFF')},"
                  f"{ab.ass_color(tpl.get('outline', '#000000'))},{ab.ass_color('#000000', 0x60)},-1,0,0,0,100,100,0,0,1,"
                  f"{ab._num(OUTLINE * size)},{ab._num(SHADOW * size)},{tail}"]
    events = [f"Dialogue: 1,{ab.ts(0)},{ab.ts(5)},Cover,,0,0,0,,{{{pos}}}" + "\\N".join(rendered)]
    if style == "box" and alpha:
        plain = "\\N".join(ab.escape_text(x) for x in lines)
        events.insert(0, f"Dialogue: 0,{ab.ts(0)},{ab.ts(5)},CoverBox,,0,0,0,,{{{pos}}}{plain}")
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    return {"ass": "\n".join(header + events) + "\n", "band": (center_y, block_h), "emoji": emoji_at}


# ── Imagen ───────────────────────────────────────────────────────────────────

def auto_time(video: Path) -> float | None:
    """Mejor segundo del clip para la portada, en caché mientras el video no cambie."""
    from media.services import reframe_adapter
    from media.services.atomic import read_json, write_json

    st = video.stat()
    key = f"{st.st_size}:{st.st_mtime_ns}"
    cache = video.with_name(_AUTO_CACHE)
    cached = read_json(cache, {}) or {}
    if cached.get("key") == key and cached.get("t") is not None:
        return float(cached["t"])
    t = reframe_adapter.best_cover_time(video)
    if t is not None:
        write_json(cache, {"key": key, "t": round(t, 3)})
    return t


def band_filter(center_y: float, block_h: float, strength: float = DIM_STRENGTH) -> str:
    """Oscurece la luma en una franja gaussiana centrada en el texto (Y de
    rango limitado: el negro es 16)."""
    sigma = max(block_h * 0.75, 120.0)
    return (f"geq=lum='16+(lum(X,Y)-16)*(1-{strength:g}*exp(-pow((Y-{center_y:.1f})/{sigma:.1f},2)))'"
            ":cb='cb(X,Y)':cr='cr(X,Y)'")


def command(video: str, t: float, out: str, *, width: int, height: int, ass: str | None, fonts_rel: str,
            effects: str | None, band: tuple[float, float] | None) -> list[str]:
    """ffmpeg para un cuadro con el texto encima. Rutas relativas al cwd."""
    from media.services.ffmpeg import ffmpeg_bin

    vf = [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}", "format=yuv420p"]
    if effects:
        vf.append(effects)
    if band:
        vf.append(band_filter(*band))
    if ass:
        vf.append(f"ass={ass}:fontsdir={fonts_rel}")
    vf.append("scale=out_range=full,format=yuvj420p")
    return [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", video,
            "-frames:v", "1", "-vf", ",".join(vf), "-q:v", "2", out]


def rendered_parts(cfolder: Path) -> list[tuple[float, float]] | None:
    """Tramos con que se hizo ``reframed.mp4`` (reframe.json): si editaste los
    tramos después del render, el video encuadrado sigue siendo el anterior."""
    from media.services.atomic import read_json

    raw = (read_json(cfolder / "reframe.json", {}) or {}).get("parts")
    try:
        parts = [(float(a), float(b)) for a, b in raw or [] if float(b) > float(a)]
    except (TypeError, ValueError):
        return None
    return parts or None


def make_cover(clip: dict, cfolder: Path) -> dict:
    """Genera ``cover.jpg`` en la carpeta del clip con sus ajustes. Devuelve
    {"path", "time" (segundo del clip usado), "auto" (si el cuadro fue
    automático)}. Lanza CoverError si el clip aún no tiene render."""
    from media.services import ass_builder, edit_doc, emoji_art, emoji_text, fonts
    from media.services.atomic import write_text
    from media.services.ffmpeg import run, video_size

    video = cfolder / "reframed.mp4"
    if not video.exists():
        raise CoverError("Renderiza el clip primero: la portada sale del video ya encuadrado.")
    settings = parse(clip.get("cover"))
    doc = edit_doc.parse(clip.get("edit"))
    parts = rendered_parts(cfolder) or edit_doc.clip_parts(clip)
    total = sum(b - a for a, b in parts)
    width, height = video_size(video)
    if not width or not height:
        raise CoverError("No se pudo leer el video del clip.")
    t = clip_offset(parts, settings["time"])
    auto = t is None
    if auto:
        t = auto_time(video)
        if t is None:
            t = min(1.0, total / 2)
    t = min(max(0.0, t), max(0.0, total - 0.05))
    tpl = ass_builder.load_template(clip.get("templateId") or ass_builder.DEFAULT_TEMPLATE)
    text = settings["text"] if settings["text"] is not None else (clip.get("hook") or "")
    _plain, char = emoji_text.split(text)
    char = char if char and emoji_art.available() else None  # sin fuente de emojis a color: portada sin emoji
    made = layout(text, tpl=tpl, width=width, height=height, position=settings["position"],
                  style=settings["style"], font=doc["font"], emoji=bool(char))
    ass, block, emoji_at = (made["ass"], made["band"], made["emoji"]) if made else ("", None, None)
    ass_name = "cover.ass"
    if ass:
        write_text(cfolder / ass_name, ass)
    tmp = cfolder / "cover.tmp.jpg"
    try:
        run(command(video.name, t, tmp.name, width=width, height=height, ass=ass_name if ass else None,
                    fonts_rel=os.path.relpath(fonts.fonts_dir(), cfolder),
                    effects=edit_doc.effects_filter(doc["effects"], width),
                    band=block if settings["dim"] else None),
            timeout=120, what="portada", cwd=cfolder)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise CoverError("ffmpeg no produjo la portada.")
        if char and emoji_at:
            paste_emoji(tmp, char, emoji_at)
        tmp.replace(cfolder / FILE)
    finally:
        tmp.unlink(missing_ok=True)
    return {"path": cfolder / FILE, "time": round(t, 3), "auto": auto}


def paste_emoji(jpg: Path, char: str, at: tuple[float, float, int]) -> bool:
    """Superpone el emoji a color (centro ``at`` = x, y, tamaño) sobre la
    portada. False si no se pudo (la portada queda sin emoji)."""
    from media.services import emoji_art
    try:
        from PIL import Image
        png = emoji_art.emoji_png(char, at[2])
        if png is None:
            return False
        with Image.open(jpg) as im:
            base = im.convert("RGB")
        icon = Image.open(png).convert("RGBA")
        base.paste(icon, (round(at[0] - icon.width / 2), round(at[1] - icon.height / 2)), icon)
        base.save(jpg, "JPEG", quality=95, subsampling=0)
        return True
    except Exception as exc:  # la portada sigue valiendo sin el emoji
        import logging
        logging.getLogger(__name__).warning("no se pudo poner el emoji en la portada: %s", exc)
        return False


def filename(clip: dict, base: str | None = None) -> str:
    """Nombre de descarga. Con ``base`` (el nombre del video, p. ej. «03 -
    Título»): «03 - Título - portada.jpg», junto a su «03 - Título.mp4».
    Sin él: «portada-<gancho>.jpg»."""
    import re
    if base:
        return f"{base} - portada.jpg"
    base = re.sub(r"[^\w\s-]", "", clip.get("hook") or clip.get("title") or "clip").strip()
    base = re.sub(r"\s+", "-", base)[:60].strip("-").lower() or "clip"
    return f"portada-{base}.jpg"


__all__ = ["parse", "merge", "clip_offset", "fit_text", "split_balanced", "accent_words", "build_ass", "layout",
           "paste_emoji",
           "make_cover", "filename", "CoverError", "FILE", "DEFAULTS"]
