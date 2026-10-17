"""Generador de subtítulos ASS animados.

* 2–3 palabras por bloque; un evento por palabra con la palabra que se
  pronuncia resaltada (color, caja o brillo según la plantilla).
* Estilo OpusClip: las palabras fuertes, los números y las que marcas a mano
  (``hl``) llevan el color de énfasis de la plantilla (services/caption_fx.py);
  la entrada del bloque («pop» o «fade») se aplica a la línea entera, una vez,
  sin escalar palabras sueltas (así la línea no se reacomoda ni vibra).
* Gancho arriba, de 0 a N s, con caja (BorderStyle 3): en una línea o en dos
  líneas equilibradas (el corte que deja la línea más larga lo más corta
  posible); si aun así no cabe, se achica la letra. Números y palabras
  fuertes van en el color de acento del gancho. El texto se limpia con
  `moments.sanitize_hook` (sin comillas ni hashtags, ≤ 10 palabras/64 car.).
* Base 1080×1920; en cuadrado u horizontal se escalan tamaños y márgenes.
* En tramos SPLIT cada palabra se centra en la unión con `\\an5` .
* Los emojis NO van en el ASS (libass los dibuja en gris): `plan_emojis`
  devuelve dónde y cuándo superponerlos como PNG (services/emoji_art.py).

Palabras de entrada relativas al clip: ``[{"w", "start", "end", "hl"?}]``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from media.config import TEMPLATES_DIR
from media.services import caption_fx, layout_ranges

PLAY_W, PLAY_H = 1080, 1920
DEFAULT_TEMPLATE = "bold-yellow"
_PUNCT_BREAK = re.compile(r"[.?!…,;:]$")
HOOK_SIDE_MARGIN = 90
HOOK_BOX_PAD = 18
HOOK_MIN_SCALE = 0.55
HOOK_MAX_SECONDS = 6.0
READ_BASE, READ_PER_WORD = 0.8, 0.32  # un titular se lee a ~3 palabras/s más la reacción
CAPTION_SIDE_MARGIN = 80
LINE_HEIGHT = 1.25
EMOJI_SCALE = 1.3


@lru_cache(maxsize=32)
def _load_template(template_id: str) -> str:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        path = TEMPLATES_DIR / f"{DEFAULT_TEMPLATE}.json"
    return path.read_text(encoding="utf-8")


def load_template(template_id: str) -> dict:
    return json.loads(_load_template(template_id or DEFAULT_TEMPLATE))


TEMPLATE_INFO_KEYS = ("id", "name", "description", "font", "highlight", "primary", "emphasis",
                      "uppercase", "animation", "box_color", "background", "entrance", "emoji")


def list_templates() -> list[dict]:
    out = []
    for p in sorted(TEMPLATES_DIR.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: t.get(k) for k in TEMPLATE_INFO_KEYS})
    return out


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB → &HAABBGGRR (alpha 0 = opaco)."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _inline(hex_color: str) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFFFFF"
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def escape_text(text: str) -> str:
    return (text or "").replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _num(x: float) -> str:
    """Número compacto para el ASS (sin decimales de sobra)."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def group_words(words: list[dict], per_group: int = 3, max_chars: int = 18,
                max_gap: float = 0.5) -> list[list[dict]]:
    """Agrupa en bloques de hasta ``per_group`` palabras, cortando en pausas y
    puntuación para que cada bloque se lea como una unidad."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if (len(cur) >= per_group or gap > max_gap or chars > max_chars
                    or _PUNCT_BREAK.search(cur[-1]["w"])):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


# ── Medida de texto ──────────────────────────────────────────────────────────

def libass_em_ratio(path: Path) -> float | None:
    """Cuánto mide el «em» respecto al tamaño ASS en libass.

    libass (como VSFilter) escala la fuente para que usWinAscent+usWinDescent
    de la tabla OS/2 midan lo que dice Fontsize: em = tamaño × unitsPerEm /
    (winAscent + winDescent). Se lee directamente del archivo (TTF/OTF);
    None si no se puede (p. ej. colecciones .ttc)."""
    import struct
    try:
        data = path.read_bytes()
        if data[:4] == b"ttcf":
            return None
        count = struct.unpack(">H", data[4:6])[0]
        tables = {}
        for i in range(count):
            tag, _cs, off, _ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
            tables[tag] = off
        upm = struct.unpack(">H", data[tables[b"head"] + 18:tables[b"head"] + 20])[0]
        win_asc, win_desc = struct.unpack(">HH", data[tables[b"OS/2"] + 74:tables[b"OS/2"] + 78])
        return upm / (win_asc + win_desc) if upm and win_asc + win_desc else None
    except (KeyError, OSError, struct.error):
        return None


@lru_cache(maxsize=32)
def _measurer(font_name: str, _fonts_version: int = 0):
    """(función ancho(texto, tamaño ASS)) con la fuente real si está; si no,
    una estimación por caracteres. Coincide con libass a ±1 % (medido)."""
    try:
        from PIL import ImageFont

        from media.services.fonts import find_font_file
        path = find_font_file(font_name)
        if path is not None:
            font = ImageFont.truetype(str(path), 200)
            ratio = libass_em_ratio(path)
            if ratio is None:
                ascent, descent = font.getmetrics()
                ratio = 200 / max(1, ascent + descent)
            return lambda text, size: font.getlength(text) / 200 * size * ratio
    except Exception:
        pass
    return lambda text, size: len(text) * size * 0.5


def _fonts_version() -> int:
    """Cambia al subir o borrar una fuente (invalida la caché de medidas)."""
    try:
        from media.config import settings
        return settings().user_fonts_dir.stat().st_mtime_ns
    except OSError:
        return 0


def text_width(text: str, font_name: str, size: float) -> float:
    return float(_measurer(font_name or "", _fonts_version())(text or "", size))


def balance_lines(words: list[str], measure, max_width: float) -> list[str]:
    """Una línea si cabe; si no, dos equilibradas: el corte que deja la línea
    más larga lo más corta posible (``measure(texto) → ancho``)."""
    text = " ".join(words)
    if len(words) < 2 or measure(text) <= max_width:
        return [text]
    best, best_longest = [text], float("inf")
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        longest = max(measure(a), measure(b))
        if longest < best_longest:
            best, best_longest = [a, b], longest
    return best


def hook_layout(text: str, *, font: str, size: float, max_width: float) -> tuple[list[str], float]:
    """(líneas, tamaño) del gancho: equilibra en dos líneas y achica la letra
    solo si la línea más larga no cabe (nunca por debajo de 55 %)."""
    words = text.split()
    if not words:
        return [], size
    lines = balance_lines(words, lambda t: text_width(t, font, size), max_width)
    longest = max(text_width(line, font, size) for line in lines)
    if longest > max_width:
        size = max(size * HOOK_MIN_SCALE, size * max_width / longest)
    return lines, size


# ── Estilos ──────────────────────────────────────────────────────────────────

def _scales(width: int, height: int) -> tuple[float, float]:
    """(escala de tamaños, escala de márgenes verticales) respecto a 1080×1920."""
    return min(width, height) / 1080, height / 1920


def _active_prefix(tpl: dict, fs: float) -> str:
    hl = _inline(tpl.get("highlight", "#FFE600"))
    anim = tpl.get("animation", "color")
    if anim == "pop":
        return f"{{\\c{hl}\\fscx88\\fscy88\\t(0,90,\\fscx106\\fscy106)}}"
    if anim == "box":
        box = _inline(tpl.get("box_color", "#7C3AED"))
        return f"{{\\c{hl}\\3c{box}\\bord{_num(14 * fs)}\\shad0}}"
    if anim == "glow":
        # Relleno de color con contorno negro nítido y un halo suave en la sombra
        # (\4c + \blur). Contorno del mismo color que el texto lo vuelve un bloque.
        return f"{{\\c{hl}\\3c&H000000&\\4c{hl}\\bord{_num(6 * fs)}\\shad{_num(4 * fs)}\\blur1.5\\fscx106\\fscy106}}"
    return f"{{\\c{hl}}}"


def _entrance(tpl: dict) -> str:
    kind = tpl.get("entrance")
    if kind == "pop":
        return "{\\fscx90\\fscy90\\t(0,140,\\fscx100\\fscy100)}"
    if kind == "fade":
        return "{\\fad(140,0)}"
    return ""


def _caption_styles(tpl: dict, font: str, fs: float, vs: float) -> list[str]:
    """Estilo del texto y, si la plantilla lleva franja de fondo, un estilo
    aparte para la caja. La caja va en su propia capa con el texto sin cortes:
    si se dibujara con el texto, cada tramo de color (palabra activa, énfasis)
    tendría su propia caja y, al ser translúcidas, se verían franjas oscuras
    donde se solapan."""
    primary = ass_color(tpl.get("primary"))
    size = round(tpl.get("size", 80) * fs)
    margin = round(CAPTION_SIDE_MARGIN * fs)
    margin_v = round(tpl.get("margin_v", 600) * vs)
    tail = f"2,{margin},{margin},{margin_v},1"
    if tpl.get("background"):
        alpha = max(0, min(255, int(tpl.get("background_alpha", 0x60))))
        box = ass_color(tpl["background"], alpha)
        pad = _num(tpl.get("background_pad", 14) * fs)
        hidden = ass_color("#000000", 0xFF)
        return [
            f"Style: Caption,{font},{size},{primary},{primary},{hidden},{hidden},"
            f"-1,0,0,0,100,100,0,0,1,0,0,{tail}",
            f"Style: CaptionBox,{font},{size},{hidden},{hidden},{box},{hidden},"
            f"-1,0,0,0,100,100,0,0,3,{pad},0,{tail}",
        ]
    return [f"Style: Caption,{font},{size},{primary},{primary},{ass_color(tpl.get('outline', '#000000'))},"
            f"{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,1,{_num(tpl.get('outline_width', 6) * fs)},"
            f"{_num(tpl.get('shadow', 2) * fs)},{tail}"]


def _hook_translucent(hook: dict) -> bool:
    return int(hook.get("box_alpha", 0)) > 0


def _hook_styles(hook: dict, font: str, fs: float, vs: float) -> list[str]:
    """Gancho con caja. Caja opaca: un solo estilo (los solapes no se notan).
    Caja translúcida: texto y caja en estilos y capas separados, como en los
    subtítulos."""
    text = ass_color(hook.get("text", "#111111"))
    alpha = max(0, min(255, int(hook.get("box_alpha", 0))))
    box = ass_color(hook.get("box", "#FFE600"), alpha)
    hidden = ass_color("#000000", 0xFF)
    size = round(hook.get("size", 62) * fs)
    side = round(HOOK_SIDE_MARGIN * fs)
    tail = f"8,{side},{side},{round(hook.get('margin_v', 260) * vs)},1"
    pad = _num(HOOK_BOX_PAD * fs)
    if not _hook_translucent(hook):
        return [f"Style: Hook,{font},{size},{text},{text},{box},{hidden},-1,0,0,0,100,100,0,0,3,{pad},0,{tail}"]
    return [
        f"Style: Hook,{font},{size},{text},{text},{hidden},{hidden},-1,0,0,0,100,100,0,0,1,0,0,{tail}",
        f"Style: HookBox,{font},{size},{hidden},{hidden},{box},{hidden},-1,0,0,0,100,100,0,0,3,{pad},0,{tail}",
    ]


def _hook_accent(tpl: dict, hook: dict) -> str:
    """Color de acento del gancho: el de la plantilla o, si no hay, el resaltado
    salvo que coincida con la caja (sería invisible)."""
    if hook.get("accent"):
        return hook["accent"]
    hl = tpl.get("highlight", "#FFE600")
    return hl if hl.lower() != str(hook.get("box", "")).lower() else hook.get("text", "#FFFFFF")


def hook_display_seconds(hook_text: str, tpl: dict, spoken: float | None = None) -> float:
    """Cuánto queda el gancho en pantalla: lo que dura la plantilla, lo que se
    tarda en leerlo (~3 palabras/s + reacción) y lo que dura el gancho hablado,
    lo mayor de los tres, con un tope de 6 s para no tapar el video."""
    from media.services.moments import hook_plain

    n = len(hook_plain(hook_text).split())
    base = float(tpl.get("hook", {}).get("duration", 3.0))
    reading = READ_BASE + READ_PER_WORD * n if n else 0.0
    return round(min(HOOK_MAX_SECONDS, max(base, reading, spoken or 0.0)), 2)


def hook_events(hook_text: str, *, tpl: dict, width: int = PLAY_W, height: int = PLAY_H,
                font: str | None = None, clip_duration: float | None = None,
                seconds: float | None = None) -> list[str]:
    """Eventos `Dialogue` del gancho ([] si no hay texto útil)."""
    from media.services.moments import hook_plain

    hook = tpl.get("hook", {})
    text = hook_plain(hook_text)  # sin emoji: libass no los dibuja a color; va aparte (`plan_hook_emoji`)
    if not text:
        return []
    if hook.get("uppercase", tpl.get("uppercase", True)):
        text = text.upper()
    fs, _vs = _scales(width, height)
    font = font or hook.get("font", tpl["font"])
    size = hook.get("size", 62) * fs
    max_width = width - 2 * HOOK_SIDE_MARGIN * fs - 2 * HOOK_BOX_PAD * fs
    lines, fitted = hook_layout(text, font=font, size=size, max_width=max_width)
    base, accent = _inline(hook.get("text", "#111111")), _inline(_hook_accent(tpl, hook))
    rendered = []
    for line in lines:
        parts = []
        for word in line.split():
            t = escape_text(word)
            if accent != base and caption_fx.is_emphasis(caption_fx.normalize_token(word)):
                parts.append(f"{{\\c{accent}}}{t}{{\\c{base}}}")
            else:
                parts.append(t)
        rendered.append(" ".join(parts))
    dur = float(seconds) if seconds else float(hook.get("duration", 3.0))
    if clip_duration:
        dur = min(dur, clip_duration)
    tags = "\\fad(120,200)" + (f"\\fs{round(fitted)}" if round(fitted) != round(size) else "")
    body = "\\N".join(rendered)
    events = [f"Dialogue: 3,{ts(0)},{ts(dur)},Hook,,0,0,0,,{{{tags}}}{body}"]
    if _hook_translucent(hook):
        plain = "\\N".join(escape_text(line) for line in lines)
        events.insert(0, f"Dialogue: 2,{ts(0)},{ts(dur)},HookBox,,0,0,0,,{{{tags}}}{plain}")
    return events


HOOK_EMOJI_SCALE = 1.5   # tamaño del emoji respecto a la letra del gancho
HOOK_EMOJI_GAP = 10      # separación con la caja del gancho (base 1080)


def plan_hook_emoji(hook_text: str, *, tpl: dict, width: int = PLAY_W, height: int = PLAY_H,
                    seconds: float | None = None, clip_duration: float | None = None) -> dict | None:
    """Emoji del gancho: ``{"emoji", "start", "end", "x", "y", "size"}`` (segundos
    del video final, píxeles del cuadro) o None si el gancho no lleva emoji.
    Va a color, centrado justo encima de la caja del gancho (que se ancla arriba
    con un margen fijo: no depende de cuántas líneas ocupe el texto) y se queda
    lo que el gancho."""
    from media.services.emoji_text import split
    from media.services.moments import sanitize_hook

    _text, char = split(sanitize_hook(hook_text))
    if not char or not _text:
        return None
    hook = tpl.get("hook", {})
    fs, vs = _scales(width, height)
    px = int(round(hook.get("size", 62) * fs * HOOK_EMOJI_SCALE))
    box_top = hook.get("margin_v", 260) * vs - HOOK_BOX_PAD * fs
    dur = float(seconds) if seconds else float(hook.get("duration", 3.0))
    if clip_duration:
        dur = min(dur, clip_duration)
    return {"emoji": char, "start": 0.0, "end": round(dur, 3), "x": int(round(width / 2 - px / 2)),
            "y": int(max(0, round(box_top - HOOK_EMOJI_GAP * fs - px))), "size": px}


# ── Bloques de subtítulos ────────────────────────────────────────────────────

def _groups(words: list[dict], tpl: dict) -> list[list[tuple[int, dict]]]:
    """Bloques con el índice de cada palabra en la lista filtrada."""
    kept = [w for w in words if str(w.get("w", "")).strip()]
    idx = {id(w): i for i, w in enumerate(kept)}
    groups = group_words(kept, int(tpl.get("words_per_group", 3)), int(tpl.get("max_chars", 18)))
    return [[(idx[id(w)], w) for w in g] for g in groups]


def _group_end(groups: list, gi: int, clip_duration: float | None) -> float:
    group = groups[gi]
    end = group[-1][1]["end"]
    if gi + 1 < len(groups):
        nxt = groups[gi + 1][0][1]["start"]
        if 0 <= nxt - end < 0.35:
            end = nxt  # sin parpadeo entre bloques seguidos
    if clip_duration:
        end = min(end, clip_duration)
    return end


def build_ass(words: list[dict], *, template_id: str = DEFAULT_TEMPLATE, hook_text: str = "",
              clip_duration: float | None = None, layout: list[dict] | None = None,
              width: int = PLAY_W, height: int = PLAY_H, font: str | None = None,
              hook_seconds: float | None = None) -> str:
    tpl = load_template(template_id)
    hook = tpl.get("hook", {})
    upper = bool(tpl.get("uppercase", True))
    splits = layout_ranges.split_ranges(layout)
    fs, vs = _scales(width, height)
    cap_font = font or tpl["font"]

    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *_caption_styles(tpl, cap_font, fs, vs),
        *_hook_styles(hook, font or hook.get("font", tpl["font"]), fs, vs),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    events: list[str] = hook_events(hook_text, tpl=tpl, width=width, height=height, font=font,
                                    clip_duration=clip_duration, seconds=hook_seconds)

    groups = _groups(words, tpl)
    flat = [w for g in groups for _, w in g]
    _emojis, emph = caption_fx.annotate(flat, emoji=False, emphasis=bool(tpl.get("emphasis")))
    emph_color = _inline(tpl.get("emphasis") or tpl.get("highlight", "#FFE600"))
    active = _active_prefix(tpl, fs)
    entrance = _entrance(tpl)
    boxed = bool(tpl.get("background"))
    for gi, group in enumerate(groups):
        group_end = _group_end(groups, gi, clip_duration)
        g_start = group[0][1]["start"]
        if boxed and group_end - g_start >= 0.02:
            seam = "{\\an5}" if layout_ranges.in_split(g_start, splits) else ""
            plain = " ".join(escape_text(w["w"].upper() if upper else w["w"]) for _, w in group)
            events.append(f"Dialogue: 0,{ts(g_start)},{ts(group_end)},CaptionBox,,0,0,0,,{seam}{entrance}{plain}")
        for i, (_, word) in enumerate(group):
            ev_start = group[0][1]["start"] if i == 0 else word["start"]
            ev_end = group[i + 1][1]["start"] if i + 1 < len(group) else group_end
            if ev_end - ev_start < 0.02:
                continue
            parts = []
            for j, (k, other) in enumerate(group):
                t = escape_text(other["w"].upper() if upper else other["w"])
                if j == i:
                    parts.append(f"{active}{t}{{\\r}}")
                elif k in emph:
                    parts.append(f"{{\\c{emph_color}}}{t}{{\\r}}")
                else:
                    parts.append(t)
            seam = "{\\an5}" if layout_ranges.in_split(ev_start, splits) else ""
            intro = entrance if i == 0 else ""
            events.append(f"Dialogue: 1,{ts(ev_start)},{ts(ev_end)},Caption,,0,0,0,,{seam}{intro}{' '.join(parts)}")
    return header + "\n" + "\n".join(events) + "\n"


def write_ass(path: Path, words: list[dict], **kwargs) -> Path:
    from media.services.atomic import write_text
    write_text(path, build_ass(words, **kwargs))
    return path


# ── Emojis (superpuestos como imagen) ────────────────────────────────────────

def plan_emojis(words: list[dict], *, template_id: str = DEFAULT_TEMPLATE, layout: list[dict] | None = None,
                width: int = PLAY_W, height: int = PLAY_H, font: str | None = None,
                clip_duration: float | None = None) -> list[dict]:
    """Emojis de contexto: ``[{"emoji", "start", "end", "x", "y", "size"}]`` en
    segundos del clip y píxeles del cuadro. Aparecen cuando se dice la palabra
    y se quedan hasta que termina su bloque, centrados encima del subtítulo."""
    tpl = load_template(template_id)
    if not tpl.get("emoji"):
        return []
    groups = _groups(words, tpl)
    flat = [w for g in groups for _, w in g]
    emojis, _ = caption_fx.annotate(flat, emoji=True, emphasis=False,
                                    max_emojis=caption_fx.emoji_budget(clip_duration))
    if not emojis:
        return []
    splits = layout_ranges.split_ranges(layout)
    fs, vs = _scales(width, height)
    upper = bool(tpl.get("uppercase", True))
    cap_font = font or tpl["font"]
    size = tpl.get("size", 80) * fs
    stroke = 0.0 if tpl.get("background") else float(tpl.get("outline_width", 6)) * fs
    usable = width - 2 * CAPTION_SIDE_MARGIN * fs
    margin_v = tpl.get("margin_v", 600) * vs
    line_h = size * LINE_HEIGHT + 2 * stroke
    emoji_px = int(round(size * EMOJI_SCALE))
    out: list[dict] = []
    for gi, group in enumerate(groups):
        group_end = _group_end(groups, gi, clip_duration)
        for k, word in group:
            char = emojis.get(k)
            if not char:
                continue
            start = float(word["start"])
            if group_end - start < 0.3:
                continue
            text = " ".join(w["w"].upper() if upper else w["w"] for _, w in group)
            lines = 1 if text_width(text, cap_font, size) + 2 * stroke <= usable else 2
            if layout_ranges.in_split(start, splits):
                top = height / 2 - lines * line_h / 2
            else:
                top = height - margin_v - lines * line_h
            out.append({"emoji": char, "start": round(start, 3), "end": round(group_end, 3),
                        "x": int(round(width / 2 - emoji_px / 2)),
                        "y": int(max(0, round(top - emoji_px - 12 * fs))), "size": emoji_px})
    for a, b in zip(out, out[1:]):  # nunca dos a la vez en el mismo sitio
        a["end"] = min(a["end"], b["start"])
    return [e for e in out if e["end"] - e["start"] >= 0.25]
