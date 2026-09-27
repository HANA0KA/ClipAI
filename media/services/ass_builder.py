"""Generador de subtítulos ASS animados (plan 6.5).

* 2–3 palabras por evento; un evento por palabra con la palabra que se
  pronuncia resaltada (color, caja o brillo según la plantilla).
* Estilo base 1080×1920, fuente de la plantilla, borde negro, `MarginV≈600`.
* Gancho: segundo estilo arriba, visible de 0 a N s, con caja (BorderStyle 3).
* En tramos SPLIT cada palabra se centra en la unión con `\\an5` — idea
  adaptada de OpenShorts `subtitles.py` (`seam_prefix`, MIT, © 2024 OpenShorts).

Palabras de entrada relativas al clip: ``[{"w", "start", "end"}]``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from media.config import TEMPLATES_DIR
from media.services import layout_ranges

PLAY_W, PLAY_H = 1080, 1920
DEFAULT_TEMPLATE = "bold-yellow"
_PUNCT_BREAK = re.compile(r"[.?!…,;:]$")


@lru_cache(maxsize=16)
def _load_template(template_id: str) -> str:
    path = TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        path = TEMPLATES_DIR / f"{DEFAULT_TEMPLATE}.json"
    return path.read_text(encoding="utf-8")


def load_template(template_id: str) -> dict:
    return json.loads(_load_template(template_id or DEFAULT_TEMPLATE))


def list_templates() -> list[dict]:
    out = []
    for p in sorted(TEMPLATES_DIR.glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        out.append({k: t.get(k) for k in ("id", "name", "description", "font", "highlight", "primary")})
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


def group_words(words: list[dict], per_group: int = 3, max_chars: int = 18,
                max_gap: float = 0.5) -> list[list[dict]]:
    """Agrupa en bloques de hasta ``per_group`` palabras, cortando en pausas y
    puntuación para que cada bloque se lea como una unidad."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
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


def _active_prefix(tpl: dict) -> str:
    hl = _inline(tpl.get("highlight", "#FFE600"))
    anim = tpl.get("animation", "color")
    if anim == "pop":
        return f"{{\\c{hl}\\fscx88\\fscy88\\t(0,90,\\fscx106\\fscy106)}}"
    if anim == "box":
        box = _inline(tpl.get("box_color", "#7C3AED"))
        return f"{{\\c{hl}\\3c{box}\\bord14\\shad0}}"
    if anim == "glow":
        # Relleno de color con contorno negro nítido y un halo suave en la sombra
        # (\4c + \blur). Contorno del mismo color que el texto lo vuelve un bloque.
        return f"{{\\c{hl}\\3c&H000000&\\4c{hl}\\bord6\\shad4\\blur1.5\\fscx106\\fscy106}}"
    return f"{{\\c{hl}}}"


def build_ass(words: list[dict], *, template_id: str = DEFAULT_TEMPLATE, hook_text: str = "",
              clip_duration: float | None = None, layout: list[dict] | None = None) -> str:
    tpl = load_template(template_id)
    hook = tpl.get("hook", {})
    upper = bool(tpl.get("uppercase", True))
    splits = layout_ranges.split_ranges(layout)

    style_caption = (
        f"Style: Caption,{tpl['font']},{tpl.get('size', 80)},{ass_color(tpl.get('primary'))},"
        f"{ass_color(tpl.get('primary'))},{ass_color(tpl.get('outline', '#000000'))},"
        f"{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,1,{tpl.get('outline_width', 6)},"
        f"{tpl.get('shadow', 2)},2,80,80,{tpl.get('margin_v', 600)},1"
    )
    style_hook = (
        f"Style: Hook,{hook.get('font', tpl['font'])},{hook.get('size', 62)},"
        f"{ass_color(hook.get('text', '#111111'))},{ass_color(hook.get('text', '#111111'))},"
        f"{ass_color(hook.get('box', '#FFE600'))},{ass_color('#000000', 0xFF)},-1,0,0,0,100,100,0,0,3,"
        f"18,0,8,90,90,{hook.get('margin_v', 260)},1"
    )
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {PLAY_W}", f"PlayResY: {PLAY_H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_caption, style_hook, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    events: list[str] = []
    text_hook = (hook_text or "").strip()
    if text_hook:
        if hook.get("uppercase", upper):
            text_hook = text_hook.upper()
        dur = float(hook.get("duration", 3.0))
        if clip_duration:
            dur = min(dur, clip_duration)
        events.append(f"Dialogue: 2,{ts(0)},{ts(dur)},Hook,,0,0,0,,{{\\fad(120,200)}}{escape_text(text_hook)}")

    active = _active_prefix(tpl)
    groups = group_words([w for w in words if w.get("w", "").strip()],
                         int(tpl.get("words_per_group", 3)), int(tpl.get("max_chars", 18)))
    for gi, group in enumerate(groups):
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        group_end = group[-1]["end"]
        if next_start is not None and 0 <= next_start - group_end < 0.35:
            group_end = next_start  # sin parpadeo entre bloques seguidos
        if clip_duration:
            group_end = min(group_end, clip_duration)
        for i, word in enumerate(group):
            ev_start = group[0]["start"] if i == 0 else word["start"]
            ev_end = group[i + 1]["start"] if i + 1 < len(group) else group_end
            if ev_end - ev_start < 0.02:
                continue
            parts = []
            for j, other in enumerate(group):
                t = escape_text(other["w"].upper() if upper else other["w"])
                parts.append(f"{active}{t}{{\\r}}" if j == i else t)
            seam = "{\\an5}" if layout_ranges.in_split(ev_start, splits) else ""
            events.append(f"Dialogue: 1,{ts(ev_start)},{ts(ev_end)},Caption,,0,0,0,,{seam}{' '.join(parts)}")
    return header + "\n" + "\n".join(events) + "\n"


def write_ass(path: Path, words: list[dict], **kwargs) -> Path:
    from media.services.atomic import write_text
    write_text(path, build_ass(words, **kwargs))
    return path
