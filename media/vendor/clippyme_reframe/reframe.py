"""Reencuadre 9:16 por escena con cámara quieta (núcleo de ClipPyMe, recortado).

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/reframe.py
(analyze_scenes_strategy, create_general_frame, _resize_to_output,
select_cover_frame, _render_global_smooth, process_video_to_vertical) y
src/clippyme/pipeline/run_ops.py (build_vfr_normalization_command).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).

Cambios respecto al original:
* `process_video_to_vertical` se parte en piezas (`normalize_vfr`,
  `track_static_targets`, `render_frames`, `open_encoder`, `mux_audio`) para
  que el adaptador pueda intercalar el diseño SPLIT de OpenShorts por cuadro.
* Fuera: modos subject/object (FrameShift), recorte por saliencia y por pesos
  de objetos, bucle streaming legacy, suavizadores savgol/kalman/L2, Ken Burns
  plegado (va en el pase final), tqdm y prints.
* Con REFRAME_STATIC_AUTO=0 la cámara sigue al sujeto con un suavizado
  exponencial simple en lugar del Savitzky-Golay original.
* Binarios de ffmpeg/ffprobe y argumentos del codificador como parámetros.
* `-vsync cfr` → `-fps_mode cfr` (FFmpeg 9 eliminó -vsync).
* REFRAME_SNAP_CENTER por defecto 0,03 (antes 0,10): el 10 % del ancho de la
  fuente es casi un tercio de un recorte 9:16 y sacaba al sujeto del cuadro.
Se conservan las protecciones: VFR→CFR, fps del lector, start_time del audio
y cuadros corruptos (se duplica el último cuadro bueno).
"""
import logging
import os
import subprocess

import cv2

from .media_probe import (audio_sync_seek_args, probe_is_variable_frame_rate,
                          probe_stream_start_time, reconcile_fps)
from .reframe_detect import compute_mouth_aspect_ratio, detect_face_candidates, detect_person_yolo
from .reframe_ops import centroid_span, collapse_scene_targets
from .reframe_track import DetectionSmoother, SmoothedCameraman, SpeakerTracker
from .scene_detection import detect_scenes, get_video_resolution

log = logging.getLogger(__name__)


def _env_float(name, default):
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def static_auto_enabled() -> bool:
    raw = (os.getenv("REFRAME_STATIC_AUTO") or "").strip().lower()
    return raw in ("1", "true", "yes", "on") if raw else True


# ── Composición de cuadros ───────────────────────────────────────────────────

def resize_to_output(img, w, h):
    """LANCZOS4 al ampliar, INTER_AREA al reducir (idea de FrameShift)."""
    src_h, src_w = img.shape[:2]
    interp = cv2.INTER_AREA if (w * h) < (src_w * src_h) else cv2.INTER_LANCZOS4
    return cv2.resize(img, (w, h), interpolation=interp)


def create_general_frame(frame, output_width, output_height):
    """Plano general: fondo desenfocado + el video completo centrado por ancho."""
    orig_h, orig_w = frame.shape[:2]
    bg_w = int(orig_w * output_height / orig_h)
    bg = cv2.resize(frame, (bg_w, output_height))
    start_x = max(0, (bg_w - output_width) // 2)
    background = bg[:, start_x:start_x + output_width]
    if background.shape[1] != output_width:
        background = cv2.resize(background, (output_width, output_height))
    # Desenfocar a baja resolución es igual de suave y mucho más barato.
    small = cv2.resize(background, (output_width // 4, output_height // 4))
    background = cv2.resize(cv2.GaussianBlur(small, (0, 0), 9), (output_width, output_height))
    fg_h = int(orig_h * output_width / orig_w)
    foreground = resize_to_output(frame, output_width, fg_h)
    out = background.copy()
    y = (output_height - fg_h) // 2
    if fg_h >= output_height:
        cy = (fg_h - output_height) // 2
        return foreground[cy:cy + output_height]
    out[y:y + fg_h, :] = foreground
    return out


def crop_frame(frame, box, output_width, output_height):
    x1, y1, x2, y2 = box
    if y2 > y1 and x2 > x1:
        return resize_to_output(frame[y1:y2, x1:x2], output_width, output_height)
    return cv2.resize(frame, (output_width, output_height))


# ── Escenas y estrategia ─────────────────────────────────────────────────────

def scene_list(video_path, fps_hint=None):
    """[(inicio, fin)] en número de cuadro + fps reconciliado con OpenCV."""
    scenes, fps = detect_scenes(video_path)
    cap = cv2.VideoCapture(video_path)
    cv_fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    fps = reconcile_fps(cv_fps, float(fps or fps_hint or 30.0))
    bounds = [(s.get_frames(), e.get_frames()) for s, e in scenes]
    if not bounds:
        bounds = [(0, total)]
    return bounds, fps, total


def analyze_scenes_strategy(video_path, scene_bounds):
    """TRACK (un rostro casi quieto) | WIDE (2+ rostros o un sujeto que se
    mueve más de REFRAME_MOTION_WIDE_THRESH) | GENERAL (sin rostros).
    Se muestrean 7 cuadros por escena."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return ['TRACK'] * len(scene_bounds)
    strategies = []
    try:
        frame_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
        frame_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
        motion_thresh = _env_float("REFRAME_MOTION_WIDE_THRESH", 0.12)
        for s_frame, e_frame in scene_bounds:
            if e_frame <= s_frame:
                strategies.append('GENERAL')
                continue
            if e_frame - s_frame < 14:
                frames_to_check = sorted({min(s_frame + 2, e_frame - 1), (s_frame + e_frame) // 2,
                                          max(e_frame - 2, s_frame)})
            else:
                step = (e_frame - s_frame) // 8
                frames_to_check = [s_frame + step * i for i in range(1, 8)]
            face_counts, primary_centers = [], []
            for f_idx in frames_to_check:
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                candidates = detect_face_candidates(frame)
                face_counts.append(len(candidates))
                if candidates:
                    px, py, pw, ph = max(candidates, key=lambda c: c['box'][2] * c['box'][3])['box']
                    primary_centers.append((px + pw / 2.0, py + ph / 2.0))
                else:
                    primary_centers.append(None)
            if not face_counts:
                strategies.append('GENERAL')
                continue
            avg_faces = sum(face_counts) / len(face_counts)
            if avg_faces < 0.4:
                strategies.append('GENERAL')
            elif max(face_counts) >= 2 and avg_faces > 1.0:
                strategies.append('WIDE')
            elif centroid_span(primary_centers, frame_w, frame_h) > motion_thresh:
                strategies.append('WIDE')
            else:
                strategies.append('TRACK')
    finally:
        cap.release()
    return strategies


# ── Pase 1: rastreo → objetivo fijo por escena ───────────────────────────────

def _ema_scene_targets(targets, scene_ids, alpha=0.08):
    """REFRAME_STATIC_AUTO=0: cámara que sigue al sujeto, suavizada."""
    out, prev, prev_sid = [], None, None
    for t, sid in zip(targets, scene_ids):
        if t is None:
            out.append(None)
            prev = None
            continue
        if prev is None or sid != prev_sid:
            prev = t
        else:
            prev = tuple(p + (v - p) * alpha for p, v in zip(prev, t))
        prev_sid = sid
        out.append(prev)
    return out


def track_static_targets(video_path, scene_bounds, strategies, cameraman, frame_hook=None,
                         hook_scenes=frozenset()):
    """Recorre el clip y devuelve, por cuadro, el objetivo (cx, cy, zoom) de la
    cámara (None en escenas que no la usan). La detección corre en cuadros
    pares de escenas TRACK/WIDE; el resto solo se decodifica (grab).

    ``frame_hook(frame_number, frame, scene_index)`` recibe los cuadros de
    las escenas en ``hook_scenes`` (lo usa el adaptador para el hablante activo).
    """
    speaker_tracker = SpeakerTracker(cooldown_frames=45)
    detection_smoother = DetectionSmoother(window_size=5)
    targets, scene_ids, per_frame_strat = [], [], []
    cap = cv2.VideoCapture(video_path)
    frame_number, current = 0, 0
    try:
        while cap.isOpened():
            if current < len(scene_bounds) - 1 and frame_number >= scene_bounds[current][1]:
                current += 1
                # Corte duro: identidades e historial de la toma anterior fuera.
                speaker_tracker.reset(frame_number)
                detection_smoother.reset()
            strat = strategies[current] if current < len(strategies) else 'TRACK'
            tracked = strat in ('TRACK', 'WIDE')
            needs_pixels = (tracked and frame_number % 2 == 0) or current in hook_scenes
            if needs_pixels:
                ret, frame = cap.read()
            else:
                ret, frame = cap.grab(), None
            if not ret:
                break
            per_frame_strat.append(strat)
            scene_ids.append(current)
            if frame_hook is not None and current in hook_scenes and frame is not None:
                frame_hook(frame_number, frame, current)
            if not tracked:
                targets.append(None)
            else:
                if frame is not None and frame_number % 2 == 0:
                    candidates = detection_smoother.smooth(detect_face_candidates(frame), frame_number)
                    for cand in candidates:
                        cand['mar'] = compute_mouth_aspect_ratio(frame, cand['box'])
                    target_box = speaker_tracker.get_target(candidates, frame_number, cameraman.video_width)
                    if target_box:
                        cameraman.update_target(target_box)
                    elif strat == 'TRACK':
                        person_box = detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target(person_box, is_person_box=True)
                        else:
                            cameraman.tick()
                    else:
                        cameraman.tick()
                targets.append((cameraman.target_center_x, cameraman.target_center_y, cameraman.target_zoom))
            frame_number += 1
    finally:
        cap.release()
    if static_auto_enabled():
        fixed = collapse_scene_targets(targets, scene_ids, per_frame_strat,
                                       x_max=cameraman.video_width, y_max=cameraman.video_height,
                                       wide_zoom=1.0, snap_center_dist=_env_float("REFRAME_SNAP_CENTER", 0.03),
                                       crop_w_at_zoom1=cameraman.max_crop_width)
    else:
        fixed = _ema_scene_targets(targets, scene_ids)
    return fixed, scene_ids


# ── Pase 2: render ───────────────────────────────────────────────────────────

def render_frames(video_path, frame_fn, write_fn):
    """Decodifica cada cuadro, lo compone con ``frame_fn(n, frame)`` y lo
    escribe. Un cuadro que falla duplica el último bueno en vez de abortar
    (y truncar el clip). Devuelve (cuadros, fallidos)."""
    cap = cv2.VideoCapture(video_path)
    n, dropped, last = 0, 0, None
    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            try:
                out = frame_fn(n, frame)
                last = out
            except Exception:
                dropped += 1
                if dropped == 1:
                    log.exception("cuadro %d falló; se duplica el anterior", n)
                out = last if last is not None else None
                if out is None:
                    raise
            write_fn(out)
            n += 1
    finally:
        cap.release()
    return n, dropped


def normalize_vfr(input_video, dest, ffmpeg="ffmpeg", ffprobe="ffprobe", video_args=()):
    """VFR → CFR antes de reencuadrar (si no, el audio se desfasa)."""
    if not probe_is_variable_frame_rate(input_video, ffprobe=ffprobe):
        return input_video
    try:
        subprocess.run([ffmpeg, "-y", "-i", input_video, "-fps_mode", "cfr", *video_args,
                        "-c:a", "copy", dest], check=True, capture_output=True, timeout=1800)
        return dest
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.warning("normalización VFR falló; se usa el original")
        return input_video


def open_encoder(out_w, out_h, fps, temp_video, ffmpeg="ffmpeg", video_args=()):
    """ffmpeg que recibe cuadros BGR crudos por stdin (encode maestro)."""
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-vcodec", "rawvideo",
           "-s", f"{out_w}x{out_h}", "-pix_fmt", "bgr24", "-r", f"{fps:.6f}", "-i", "-",
           *video_args, "-fps_mode", "cfr", "-an", temp_video]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def mux_audio(input_video, temp_video, final_output, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    """Une el video reencuadrado con el audio original, compensando el
    start_time del video; ``-shortest`` evita colas congeladas."""
    seek = audio_sync_seek_args(probe_stream_start_time(input_video, 'v:0', ffprobe=ffprobe))
    base = [ffmpeg, "-y", "-loglevel", "error", "-i", temp_video, *seek, "-i", input_video,
            "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy"]
    for audio in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
        proc = subprocess.run([*base, *audio, "-shortest", final_output], capture_output=True, text=True)
        if proc.returncode == 0:
            return True
    raise RuntimeError(f"mezcla de audio falló: {proc.stderr[-500:]}")


def make_cameraman(video_path, out_w, out_h):
    w, h = get_video_resolution(video_path)
    return SmoothedCameraman(out_w, out_h, w, h, aspect_ratio=out_w / out_h), w, h


# ── Portada ──────────────────────────────────────────────────────────────────

def select_cover_frame(video_path, cover_path):
    """Mejor cuadro para la miniatura: rostro + nitidez + buena exposición."""
    cap = cv2.VideoCapture(video_path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0 or fps <= 0:
            return None
        best_score, best = -1.0, None
        for idx in range(0, total, max(1, int(fps))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            score = 50.0 if detect_face_candidates(frame) else 0.0
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score += min(30.0, cv2.Laplacian(gray, cv2.CV_64F).var() / 100 * 30)
            mean = gray.mean()
            score += 20 if 80 < mean < 200 else 10 if 50 < mean < 230 else 0
            if score > best_score:
                best_score, best = score, frame.copy()
    finally:
        cap.release()
    if best is None:
        return None
    cv2.imwrite(str(cover_path), best, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return cover_path


__all__ = [
    "analyze_scenes_strategy", "create_general_frame", "crop_frame", "make_cameraman",
    "mux_audio", "normalize_vfr", "open_encoder", "render_frames", "resize_to_output",
    "scene_list", "select_cover_frame", "track_static_targets",
]
