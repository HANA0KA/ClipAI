"""Documento de edición del clip (estudio de edición). Funciones puras.

Vive en la columna ``Clip.edit`` (JSON). Lo escribe la web
(web/lib/edit-doc.ts, misma forma y mismos límites) y lo lee el render:

    {
      "version": 1,
      "segments": [{"id": "s1", "start": 12.3, "end": 40.1}, ...],  # s. del video fuente, en orden de reproducción
      "framing": {"mode": "auto"|"manual", "aspect": "vertical"|"square"|"original",
                  "fit": "cover"|"contain", "zoom": 1..3, "x": 0..1, "y": 0..1},
      "effects": {"brightness": 40..180, "contrast": 40..180, "saturation": 0..220,
                  "blur": 0..8, "hue": -180..180},
      "audio": {"volume": 0..2, "muted": bool},
      "preset": "tiktok"|"reels"|"shorts",
      "font": "Montserrat ExtraBold" | null,         # sustituye la fuente de la plantilla
      "punch": true,                                 # acercamientos en las palabras fuertes
      "hookSeconds": null                            # gancho en pantalla: null = automático, 1,5–8 s
    }

Sin ``segments`` el clip usa sus bordes de siempre (startSec/endSec y, si
está activada, la frase más fuerte delante). Valores fuera de rango se
recortan y las claves desconocidas se ignoran: un JSON viejo o a medias nunca
rompe un render.
"""
from __future__ import annotations

import json
import math
from typing import Any

MAX_SEGMENTS = 20
MIN_SEGMENT = 0.2
ASPECTS = ("vertical", "square", "original")
PRESET_MAXRATE = {"tiktok": "10M", "reels": "12M", "shorts": "10M"}
DEFAULT_FRAMING = {"mode": "auto", "aspect": "vertical", "fit": "cover", "zoom": 1.0, "x": 0.5, "y": 0.5}
DEFAULT_EFFECTS = {"brightness": 100.0, "contrast": 100.0, "saturation": 100.0, "blur": 0.0, "hue": 0.0}
DEFAULT_AUDIO = {"volume": 1.0, "muted": False}
_EFFECT_LIMITS = {"brightness": (40, 180), "contrast": (40, 180), "saturation": (0, 220),
                  "blur": (0, 8), "hue": (-180, 180)}


def _num(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return max(lo, min(hi, x))


def parse(raw: str | dict | None) -> dict:
    """JSON de la columna → documento normalizado (siempre completo)."""
    data: dict = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            data = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            data = {}

    segments = []
    for seg in (data.get("segments") or [])[:MAX_SEGMENTS]:
        if not isinstance(seg, dict):
            continue
        s = _num(seg.get("start"), 0, 1e7, -1)
        e = _num(seg.get("end"), 0, 1e7, -1)
        if s >= 0 and e - s >= MIN_SEGMENT:
            segments.append((round(s, 3), round(e, 3)))

    f = data.get("framing") if isinstance(data.get("framing"), dict) else {}
    framing = {
        "mode": "manual" if f.get("mode") == "manual" else "auto",
        "aspect": f.get("aspect") if f.get("aspect") in ASPECTS else "vertical",
        "fit": "contain" if f.get("fit") == "contain" else "cover",
        "zoom": _num(f.get("zoom"), 1, 3, 1.0),
        "x": _num(f.get("x"), 0, 1, 0.5),
        "y": _num(f.get("y"), 0, 1, 0.5),
    }
    fx = data.get("effects") if isinstance(data.get("effects"), dict) else {}
    effects = {k: _num(fx.get(k), lo, hi, DEFAULT_EFFECTS[k]) for k, (lo, hi) in _EFFECT_LIMITS.items()}
    au = data.get("audio") if isinstance(data.get("audio"), dict) else {}
    audio = {"volume": _num(au.get("volume"), 0, 2, 1.0), "muted": bool(au.get("muted", False))}
    preset = data.get("preset") if data.get("preset") in PRESET_MAXRATE else "tiktok"
    font = data.get("font") if isinstance(data.get("font"), str) and data.get("font").strip() else None
    if font and ("," in font or len(font) > 80):
        font = None  # una coma rompería la línea Style del ASS
    punch = data.get("punch", True) is not False
    hook_seconds = None if data.get("hookSeconds") in (None, "") else _num(data.get("hookSeconds"), 1.5, 8, 0)
    return {"version": 1, "segments": segments or None, "framing": framing, "effects": effects,
            "audio": audio, "preset": preset, "font": font.strip() if font else None, "punch": punch,
            "hookSeconds": hook_seconds or None}


def clip_parts(clip: dict, doc: dict | None = None) -> list[tuple[float, float]]:
    """Tramos del video fuente que forman el clip, en orden de reproducción."""
    doc = doc if doc is not None else parse(clip.get("edit"))
    if doc.get("segments"):
        return list(doc["segments"])
    parts = []
    if clip.get("prependBestLine") and clip.get("bestLineStart") is not None and clip.get("bestLineEnd"):
        parts.append((float(clip["bestLineStart"]), float(clip["bestLineEnd"])))
    parts.append((float(clip["startSec"]), float(clip["endSec"])))
    return parts


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def output_size(aspect: str, src_w: int, src_h: int) -> tuple[int, int]:
    """Tamaño del MP4 final. «original» conserva la proporción del video
    (lado largo ≤ 1920)."""
    if aspect == "square":
        return 1080, 1080
    if aspect == "original" and src_w > 0 and src_h > 0:
        scale = min(1.0, 1920 / max(src_w, src_h))
        return _even(src_w * scale), _even(src_h * scale)
    return 1080, 1920


def framing_geometry(sw: int, sh: int, w: int, h: int, fit: str, zoom: float, x: float, y: float) -> dict:
    """Encuadre manual (misma fórmula que la vista previa de la web):
    se escala el video (llenar o encajar) × zoom, se recorta lo que sobra con
    el ancla (x, y) y lo que falta se rellena con fondo desenfocado."""
    base = (max if fit == "cover" else min)(w / sw, h / sh) * zoom
    rw, rh = _even(sw * base), _even(sh * base)
    cw, ch = min(w, rw), min(h, rh)
    return {"rw": rw, "rh": rh, "cw": cw, "ch": ch,
            "cx": int(round((rw - cw) * x)), "cy": int(round((rh - ch) * y)),
            "ox": int(round((w - cw) * x)), "oy": int(round((h - ch) * y)),
            "fills": cw == w and ch == h}


def framing_filter(sw: int, sh: int, w: int, h: int, framing: dict) -> str:
    """Filtergraph ``[0:v] → [v]`` del encuadre manual."""
    g = framing_geometry(sw, sh, w, h, framing["fit"], framing["zoom"], framing["x"], framing["y"])
    fg = f"scale={g['rw']}:{g['rh']}:flags=lanczos,crop={g['cw']}:{g['ch']}:{g['cx']}:{g['cy']}"
    if g["fills"]:
        return f"[0:v]{fg},setsar=1[v]"
    bw, bh = _even(w / 4), _even(h / 4)
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"scale={bw}:{bh},gblur=sigma=6,scale={w}:{h},setsar=1[bg];"
            f"[b]{fg},setsar=1[fg];[bg][fg]overlay={g['ox']}:{g['oy']},setsar=1[v]")


def effects_filter(effects: dict, width: int) -> str | None:
    """Filtros de color con la misma matemática que CSS (brightness, contrast,
    saturate, hue-rotate, blur) para que la vista previa y el render coincidan.
    None si todo está en su valor por defecto.

    Brillo y contraste de CSS son afines por canal RGB (v·g + o). Aplicado a
    R, G y B por igual, en YUV de rango limitado equivale a Y' = 16 + g·(Y−16)
    + (219/255)·o y U', V' = 128 + g·(U−128): se hace con `lutyuv` sin pasar a
    RGB. Pasar a RGB (`lutrgb`) dejaba la imagen en RGB y cada superposición
    posterior (emojis) convertía el cuadro entero: 5× más lento.
    """
    if all(abs(effects.get(k, v) - v) < 1e-6 for k, v in DEFAULT_EFFECTS.items()):
        return None
    b, c = effects["brightness"] / 100, effects["contrast"] / 100
    parts = []
    if abs(b - 1) > 1e-6 or abs(c - 1) > 1e-6:
        gain, offset = b * c, 255 * 0.5 * (1 - c)
        y = f"clip(16+{gain:.4f}*(val-16)+{offset * 219 / 255:.2f},16,235)"
        uv = f"clip(128+{gain:.4f}*(val-128),16,240)"
        parts.append(f"lutyuv=y='{y}':u='{uv}':v='{uv}'")  # entre comillas: las comas no cortan
    if abs(effects["saturation"] - 100) > 1e-6 or abs(effects["hue"]) > 1e-6:
        parts.append(f"hue=h={effects['hue']:.1f}:s={effects['saturation'] / 100:.3f}")
    if effects["blur"] > 0:
        parts.append(f"gblur=sigma={effects['blur'] * width / 1080:.2f}")
    if not parts:
        return None
    return ",".join(parts) + ",format=yuv420p"


def audio_filter(audio: dict) -> str | None:
    """Ganancia final (después de normalizar el volumen). None = sin cambios."""
    if audio.get("muted"):
        return "volume=0"
    v = float(audio.get("volume", 1.0))
    return None if abs(v - 1.0) < 1e-6 else f"volume={v:.3f}"


def maxrate_args(preset: str) -> list[str]:
    rate = PRESET_MAXRATE.get(preset, PRESET_MAXRATE["tiktok"])
    n = int(rate.rstrip("M"))
    return ["-maxrate", rate, "-bufsize", f"{n * 2}M"]


def original_snapshot(clip: dict, captions: dict | None) -> dict:
    """Estado del clip tal como salió del análisis, para «Restaurar original»
    (misma forma que web/lib/edit-doc.ts `originalFromClip`)."""
    parts = clip_parts(clip, parse(None))
    return {
        "version": 1,
        "hook": clip.get("hook") or "", "title": clip.get("title") or "",
        "description": clip.get("description") or "", "hashtags": clip.get("hashtags") or "",
        "templateId": clip.get("templateId") or "bold-yellow", "layoutMode": clip.get("layoutMode") or "auto",
        "smartCut": bool(clip.get("smartCut")),
        "segments": [{"id": f"s{i + 1}", "start": s, "end": e} for i, (s, e) in enumerate(parts)],
        "words": [{"t": round(float(w["start"]), 3), "w": w.get("w", ""), "hl": bool(w.get("hl"))}
                  for w in (captions or {}).get("words") or []],
    }


__all__ = ["parse", "clip_parts", "output_size", "framing_geometry", "framing_filter", "effects_filter",
           "audio_filter", "maxrate_args", "original_snapshot", "PRESET_MAXRATE", "DEFAULT_FRAMING",
           "DEFAULT_EFFECTS", "DEFAULT_AUDIO"]
