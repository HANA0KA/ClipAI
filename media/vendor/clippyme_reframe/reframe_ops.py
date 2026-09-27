"""Matemática pura de encuadre (sin cv2).

Copiado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/reframe_ops.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: solo las funciones de la política de cámara quieta
(zoom_for_face_height, centroid_span, collapse_scene_targets, drift_to_center);
fuera OneEuro, savgol, Kalman, L2, PanSmoother y saliencia. En
collapse_scene_targets se añade `crop_w_at_zoom1` para mantener dentro del
recorte los dos extremos del recorrido del sujeto cuando caben.
"""
from __future__ import annotations

import numpy as np


def zoom_for_face_height(face_h: float, max_crop_h: float, target_occupancy: float = 0.4,
                         min_zoom: float = 1.0, max_zoom: float = 1.6) -> float:
    """Zoom que hace que la cara ocupe ``target_occupancy`` de la altura del
    recorte, acotado a [min_zoom, max_zoom]."""
    if face_h <= 0:
        return min_zoom
    zoom = max_crop_h * target_occupancy / face_h
    return max(min_zoom, min(zoom, max_zoom))


def centroid_span(centers, frame_w: float, frame_h: float) -> float:
    """Recorrido normalizado del centro de un sujeto en una escena: 0 = quieto."""
    pts = [c for c in centers if c is not None]
    if len(pts) < 2 or frame_w <= 0 or frame_h <= 0:
        return 0.0
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return max((max(xs) - min(xs)) / frame_w, (max(ys) - min(ys)) / frame_h)


def collapse_scene_targets(targets, scene_ids, strategies, *, x_max: float, y_max: float,
                           wide_zoom: float = 1.0, track_zoom_cap: float = 1.35,
                           snap_center_dist: float = 0.10, crop_w_at_zoom1: float | None = None):
    """Una sola vista fija (cx, cy, zoom) por escena → cámara quieta.

    TRACK: mediana del centro del sujeto, zoom mediano acotado a
    ``track_zoom_cap``. WIDE: mediana del centro con zoom ``wide_zoom``.
    Un punto a menos de ``snap_center_dist`` del centro se centra exacto.
    """
    n = len(targets)
    out = [None] * n
    i = 0
    while i < n:
        if targets[i] is None:
            i += 1
            continue
        j = i
        sid = scene_ids[i]
        while j < n and targets[j] is not None and scene_ids[j] == sid:
            j += 1
        seg = targets[i:j]
        strat = strategies[i] if i < len(strategies) else 'TRACK'
        cx = float(np.median([t[0] for t in seg]))
        cy = float(np.median([t[1] for t in seg]))
        if strat == 'WIDE':
            zoom = float(wide_zoom)
        else:
            zoom = min(float(np.median([t[2] for t in seg])), float(track_zoom_cap))
        if abs(cx - x_max / 2.0) <= snap_center_dist * x_max:
            cx = x_max / 2.0
        if abs(cy - y_max / 2.0) <= snap_center_dist * y_max:
            cy = y_max / 2.0
        if crop_w_at_zoom1:
            # ClipAI: si el recorrido del sujeto cabe en el recorte, que sus dos
            # extremos queden dentro (la mediana sola puede dejar uno al borde).
            w = crop_w_at_zoom1 / max(zoom, 1e-6)
            xs = [t[0] for t in seg]
            lo_x, hi_x = max(xs) - 0.4 * w, min(xs) + 0.4 * w
            if lo_x <= hi_x:
                cx = min(max(cx, lo_x), hi_x)
        for k in range(j - i):
            out[i + k] = (cx, cy, zoom)
        i = j
    return out


def drift_to_center(current: float, center: float, frames_since_seen: int,
                    hold_frames: int = 90, drift_rate: float = 0.05) -> float:
    """Sujeto perdido: mantener la última posición `hold_frames` cuadros y
    luego acercarse al centro un `drift_rate` por cuadro."""
    if frames_since_seen <= hold_frames:
        return current
    return current + (center - current) * drift_rate
