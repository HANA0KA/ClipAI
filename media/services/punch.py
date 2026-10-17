"""Acercamientos en las palabras fuertes («punch-in»). Funciones puras.

Un plano fijo durante 60 s es lo más «sin editar» que puede tener un clip
vertical. En los momentos que cargan el clip se hace un acercamiento corto:
entra rápido, se mantiene y sale lento (como lo haría un operador), y va
sobre el zoom lento del plano, en el mismo `zoompan` (una sola pasada).

Los momentos salen de las palabras: las que marcaste a mano primero, luego
cifras y porcentajes, luego las palabras fuertes (services/caption_fx.py).
Como mucho uno cada 18 s: con menos separación parece un tic.

Adaptado de OpenShorts — https://github.com/mutonby/openshorts
Ruta original: punch_in.py (zoom_curve, _ease, MAX_ZOOM, RISE/HOLD/FALL,
MIN_GAP_SECONDS). Copyright (c) 2024 OpenShorts — Licencia MIT (ver
media/vendor/NOTICE.md).
Cambios: los momentos vienen del texto y no de la envolvente de audio (el
propio OpenShorts lo señala como mejor fuente); la curva se escribe como
expresión de `zoompan` en vez de comandos por cuadro para el recorte.
"""
from __future__ import annotations

from media.services import caption_fx, layout_ranges

MAX_ZOOM = 1.12          # 12 %: se nota como intención, sin cortar la cabeza
RISE, HOLD, FALL = 0.25, 1.30, 0.55
SPAN = RISE + HOLD + FALL
MIN_GAP = 18.0           # medido en OpenShorts: 18 s da ~3 por minuto, nunca más
START_GUARD = 1.5        # no en el primer segundo y medio (entra el gancho)
SKIP_LAYOUTS = {"split", "general"}  # dos personas apiladas o plano con fondo desenfocado


def beat_times(words: list[dict], duration: float, *, layout: list[dict] | None = None,
               gap: float = MIN_GAP) -> list[float]:
    """Segundos del clip donde empieza cada acercamiento, en orden."""
    if duration <= 0 or not words:
        return []
    _emoji, emph = caption_fx.annotate(words, emoji=False, emphasis=True)
    skip = [(r["start"], r["end"]) for r in layout_ranges.normalise(layout) if r["layout"] in SKIP_LAYOUTS]
    ranked = []
    for i in sorted(emph):
        w = words[i]
        t = float(w["start"])
        if t < START_GUARD or t + SPAN > duration:
            continue
        if any(s < t + SPAN and t < e for s, e in skip):  # el acercamiento no toca esos tramos
            continue
        token = caption_fx.normalize_token(str(w.get("w", "")))
        priority = 0 if w.get("hl") else 1 if any(ch.isdigit() for ch in token) else 2
        ranked.append((priority, t))
    chosen: list[float] = []
    for _priority, t in sorted(ranked):
        if all(abs(t - c) >= gap for c in chosen):
            chosen.append(round(t, 3))
    return sorted(chosen)


def zoom_expression(beats: list[float], fps: int, max_zoom: float = MAX_ZOOM) -> str | None:
    """Factor multiplicativo del zoom en función del cuadro de salida (`on`)
    para `zoompan`: 1 fuera de los acercamientos. Curva suave (smoothstep).
    Va entre comillas simples en el filtro, así que las comas no cortan."""
    if not beats or max_zoom <= 1.0:
        return None
    terms = []
    for a in beats:
        u = f"(on/{fps}-{a:.3f})"
        x1 = f"({u}/{RISE})"
        x2 = f"(({u}-{RISE + HOLD:.3f})/{FALL})"
        terms.append(
            f"if(between({u},0,{RISE}),{x1}*{x1}*(3-2*{x1}),"
            f"if(between({u},{RISE},{RISE + HOLD:.3f}),1,"
            f"if(between({u},{RISE + HOLD:.3f},{SPAN:.3f}),1-{x2}*{x2}*(3-2*{x2}),0)))")
    return f"(1+{max_zoom - 1:.3f}*({'+'.join(terms)}))"


def curve(t: float, beats: list[float], max_zoom: float = MAX_ZOOM) -> float:
    """El mismo factor evaluado en Python (para pruebas y la vista previa)."""
    def ease(x: float) -> float:
        x = min(max(x, 0.0), 1.0)
        return x * x * (3 - 2 * x)

    amount = 0.0
    for a in beats:
        u = t - a
        if 0 <= u <= RISE:
            amount += ease(u / RISE)
        elif RISE < u <= RISE + HOLD:
            amount += 1.0
        elif RISE + HOLD < u <= SPAN:
            amount += 1 - ease((u - RISE - HOLD) / FALL)
    return 1 + (max_zoom - 1) * amount


__all__ = ["beat_times", "zoom_expression", "curve", "MAX_ZOOM", "MIN_GAP"]
