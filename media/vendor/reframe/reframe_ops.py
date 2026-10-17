"""Matemática pura de encuadre (sin cv2).

Copiado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/reframe_ops.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: solo las funciones de la política de cámara quieta
(zoom_for_face_height, centroid_span, collapse_scene_targets, drift_to_center);
fuera OneEuro, savgol, Kalman, L2, PanSmoother y saliencia. En
collapse_scene_targets se añade `crop_w_at_zoom1` para mantener dentro del
recorte los dos extremos del recorrido del sujeto cuando caben.
ClipAI: estrategia FOLLOW (un sujeto que se mueve) con `follow_path`: cámara
quieta mientras el sujeto sigue en la zona central y paneo suave cuando sale.
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


def _median_filter(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) < 3:
        return x
    pad = k // 2
    padded = np.pad(x, pad, mode="edge")
    return np.array([np.median(padded[i:i + k]) for i in range(len(x))])


def _gaussian(x: np.ndarray, sigma: float) -> np.ndarray:
    """Suavizado de fase cero (sin retraso): la escena entera ya se conoce."""
    if sigma < 0.5 or len(x) < 3:
        return x
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(x, r, mode="edge"), k, mode="valid")


def _fill_invalid(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Interpola los cuadros no válidos entre los válidos (bordes: el más cercano)."""
    idx = np.flatnonzero(valid)
    if len(idx) < 2 or valid.all():
        return x
    return np.interp(np.arange(len(x)), idx, x[idx])


def _short_excursions(x: np.ndarray, center: float, far: float, min_len: int) -> np.ndarray:
    """Máscara de cuadros válidos sin los desvíos breves (menos de ``min_len``
    cuadros a más de ``far`` de ``center``): el detector se fue un momento a
    otra cara (público en primer plano), no es el sujeto moviéndose."""
    ok = np.ones(len(x), dtype=bool)
    away = np.abs(x - center) > far
    i = 0
    while i < len(x):
        if not away[i]:
            i += 1
            continue
        j = i
        while j < len(x) and away[j]:
            j += 1
        if j - i < min_len:
            ok[i:j] = False
        i = j
    return ok


def follow_path(xs, *, fps: float, crop_w: float, x_max: float, deadzone: float = 0.16,
                smooth_s: float = 0.6, max_speed: float = 0.5, settle_s: float = 1.0,
                recenter: float = 0.03, valid=None, excursion_s: float = 2.0) -> list[float]:
    """Centro horizontal del recorte, cuadro a cuadro, para seguir a un sujeto
    que se mueve sin tirones (ClipAI):

    0. ``valid`` (opcional) marca los cuadros con detección real: el resto
       (sin rostro, objetivo retenido) se interpola; y se ignoran los desvíos
       de menos de ``excursion_s`` lejos del sujeto principal;
    1. mediana corta (0,3 s) contra saltos del detector;
    2. zona muerta: la cámara no se mueve mientras el sujeto esté a menos de
       ``deadzone`` del ancho del recorte respecto al centro; al salir, lo
       acompaña justo lo necesario, y si se queda quieto ``settle_s`` s la
       cámara lo vuelve a centrar despacio (``recenter`` por cuadro);
    3. gaussiana de fase cero (``smooth_s`` s) para arrancar y frenar suave;
    4. tope de velocidad: ``max_speed`` anchos de recorte por segundo;
    5. nunca fuera del cuadro.
    """
    x = np.asarray([float(v) for v in xs], dtype=float)
    n = len(x)
    if n == 0:
        return []
    fps = fps if fps and fps > 0 else 30.0
    ok = np.ones(n, dtype=bool) if valid is None else np.asarray(valid, dtype=bool)[:n]
    if ok.sum() >= 2:
        x = _fill_invalid(x, ok)
        ok &= _short_excursions(x, float(np.median(x[ok])), 0.5 * crop_w, int(fps * excursion_s))
        if ok.sum() >= 2:
            x = _fill_invalid(x, ok)
    x = _median_filter(x, max(1, int(fps * 0.3)) | 1)
    dz = deadzone * crop_w
    cam = np.empty(n)
    c = float(np.median(x[:max(1, int(fps * 0.5))]))
    settle, still = max(1, int(fps * settle_s)), 0
    for i in range(n):
        d = x[i] - c
        if d > dz:
            c, still = x[i] - dz, 0
        elif d < -dz:
            c, still = x[i] + dz, 0
        else:
            still = still + 1 if i and abs(x[i] - x[i - 1]) < dz * 0.05 else 0
            if still >= settle:
                c += (x[i] - c) * recenter
        cam[i] = c
    cam = _gaussian(cam, smooth_s * fps)
    vmax = max_speed * crop_w / fps
    for i in range(1, n):
        cam[i] = min(max(cam[i], cam[i - 1] - vmax), cam[i - 1] + vmax)
    half = crop_w / 2.0
    lo, hi = half, max(half, x_max - half)
    return [float(min(max(v, lo), hi)) for v in cam]


def collapse_scene_targets(targets, scene_ids, strategies, *, x_max: float, y_max: float,
                           wide_zoom: float = 1.0, track_zoom_cap: float = 1.35,
                           snap_center_dist: float = 0.10, crop_w_at_zoom1: float | None = None,
                           fps: float = 30.0, follow_zoom_cap: float = 1.15, follow: bool = False,
                           follow_spread: float = 0.7, seen=None, min_seen: float = 0.25):
    """Una sola vista fija (cx, cy, zoom) por escena → cámara quieta.

    TRACK: mediana del centro del sujeto, zoom mediano acotado a
    ``track_zoom_cap``. WIDE: mediana del centro con zoom ``wide_zoom``.
    FOLLOW (ClipAI): la cámara sigue al sujeto con `follow_path` (altura y
    zoom fijos por escena, zoom acotado a ``follow_zoom_cap`` para dejarle aire).
    Con ``follow``, una escena TRACK cuyo sujeto recorre (percentiles 5–95 de
    todo el rastreo, no solo las 7 muestras de la clasificación) más de
    ``follow_spread`` del ancho del recorte también pasa a FOLLOW: fija lo
    perdería. ``seen`` (ClipAI, opcional) marca los cuadros con detección
    real y confirmada: en TRACK y FOLLOW las medianas y recorridos se calculan
    solo con ellos (sin el centro por defecto, el objetivo retenido ni objetos
    con forma de cara); una escena con menos de ``min_seen`` confirmados, y los
    grupos (WIDE), se encuadran como antes.
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
        # Grupos (WIDE) como siempre: todas las posiciones; una persona, solo las confirmadas.
        valid = ([bool(seen[k]) for k in range(i, j)] if seen is not None and strat != 'WIDE'
                 else [True] * (j - i))
        core = [t for t, v in zip(seg, valid) if v]
        if len(core) < max(3, min_seen * len(seg)):
            # Sin detecciones confirmadas suficientes (``min_seen`` de la escena):
            # como antes (todas las posiciones) y, si iba a seguir, plano abierto
            # fijo: no hay a quién seguir con certeza.
            core, valid = seg, [True] * (j - i)
            if strat == 'FOLLOW':
                strat = 'WIDE'
        cx = float(np.median([t[0] for t in core]))
        cy = float(np.median([t[1] for t in core]))
        if follow and strat == 'TRACK' and len(core) > 1:
            zoom_t = min(float(np.median([t[2] for t in core])), float(track_zoom_cap))
            xs_core = np.asarray([t[0] for t in core])
            keep = _short_excursions(xs_core, cx, 0.5 * (crop_w_at_zoom1 or x_max) / max(zoom_t, 1e-6),
                                     int(fps * 2.0))
            p5, p95 = np.percentile(xs_core[keep] if keep.sum() >= 2 else xs_core, [5, 95])
            if p95 - p5 > follow_spread * (crop_w_at_zoom1 or x_max) / max(zoom_t, 1e-6):
                strat = 'FOLLOW'
        if strat == 'FOLLOW':
            zoom = min(float(np.median([t[2] for t in core])), float(follow_zoom_cap))
            crop_w = (crop_w_at_zoom1 or x_max) / max(zoom, 1e-6)
            path = follow_path([t[0] for t in seg], fps=fps, crop_w=crop_w, x_max=x_max, valid=valid)
            for k in range(j - i):
                out[i + k] = (path[k], cy, zoom)
            i = j
            continue
        if strat == 'WIDE':
            zoom = float(wide_zoom)
        else:
            zoom = min(float(np.median([t[2] for t in core])), float(track_zoom_cap))
        if abs(cx - x_max / 2.0) <= snap_center_dist * x_max:
            cx = x_max / 2.0
        if abs(cy - y_max / 2.0) <= snap_center_dist * y_max:
            cy = y_max / 2.0
        if crop_w_at_zoom1:
            # ClipAI: si el recorrido del sujeto cabe en el recorte, que sus dos
            # extremos queden dentro (la mediana sola puede dejar uno al borde).
            w = crop_w_at_zoom1 / max(zoom, 1e-6)
            xs = [t[0] for t in core]
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
