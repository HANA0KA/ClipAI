"""Reencuadre 9:16 — contrato propio, implementación prestada.

Única puerta hacia `media/vendor/reframe` (ClipPyMe, MIT). Además
porta el diseño SPLIT y el hablante activo de OpenShorts:

Adaptado de OpenShorts — https://github.com/mutonby/openshorts
Rutas originales: split_layout.py (dedupe_faces, _two_largest, _centre,
analyze_scene, split_geometry, detect_split_scenes y sus constantes),
frame_sampler.py (read_at) y active_speaker.py (mouth_region, audio_envelope,
normalise_activity, attribute_windows, hold).
Copyright (c) 2024 OpenShorts — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: SPLIT se compone por cuadro en numpy dentro del mismo pase de render
(sin filtergraph vstack aparte); se evalúa sobre escenas que ClipPyMe marca
WIDE; no se aplica a planos de público (3+ rostros grandes); el hablante
activo se mide durante el pase de rastreo.

Diseños por escena: TRACK (un rostro, recorte fijo), FOLLOW (un sujeto que se
mueve: la cámara lo sigue con paneo suave), SPLIT (dos rostros en ≥50 % de los
cuadros, apilados), WIDE (varios rostros, recorte abierto fijo), GENERAL (sin
rostros: video centrado sobre fondo desenfocado).
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from media.services import layout_ranges
from media.services.atomic import write_json
from media.services.ffmpeg import ffmpeg_bin, ffprobe_bin, lower_priority, video_args

log = logging.getLogger(__name__)

MODES = ("auto", "track", "split", "wide", "off")
# Sube cuando cambia el encuadre automático: invalida la caché de reencuadre de
# los clips (render.py la incluye en su clave). 2 = cámara que sigue (FOLLOW) y
# solo detecciones confirmadas.
ENGINE_VERSION = 2


@dataclass
class ReframeResult:
    output: Path  # clip 1080x1920
    layout_ranges: list  # [{"start": 0.0, "end": 7.4, "layout": "track"}, ...]
    scenes: list = field(default_factory=list)  # detalle por escena (crop.json)


# ── SPLIT ────────────────────────────────────────────────────

MIN_COEXISTENCE = 0.5     # fracción de cuadros con AMBOS rostros (dos-shot real)
MIN_SEPARATION = 0.20     # separación horizontal mínima entre rostros
MIN_FACE_WIDTH = 0.045    # rostros menores son público/fondo
MIN_SCENE_SECONDS = 2.5   # una pantalla dividida más corta parece un fallo
MAX_FACE_OVERLAP = 0.30
SECONDS_PER_SAMPLE = 1.5
MIN_SAMPLES, MAX_SAMPLES = 8, 24


def split_enabled() -> bool:
    return (os.getenv("SPLIT_LAYOUT") or "1").strip().lower() not in ("0", "false", "no", "off")


def speaker_cut_enabled() -> bool:
    return (os.getenv("SPEAKER_CUT") or "0").strip().lower() in ("1", "true", "yes", "on")


def split_tightness() -> float:
    try:
        return float(os.getenv("SPLIT_TIGHTNESS") or 0.8)
    except ValueError:
        return 0.8


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def dedupe_faces(candidates, threshold=MAX_FACE_OVERLAP):
    kept = []
    for cand in sorted(candidates, key=lambda c: c['box'][2] * c['box'][3], reverse=True):
        if all(_iou(cand['box'], k['box']) <= threshold for k in kept):
            kept.append(cand)
    return kept


def _two_largest(candidates, frame_w):
    big = [c for c in dedupe_faces(candidates) if c['box'][2] >= MIN_FACE_WIDTH * frame_w]
    if len(big) < 2:
        return None
    big.sort(key=lambda c: c['score'], reverse=True)
    return tuple(sorted(big[:2], key=lambda c: c['box'][0]))


def _centre(box):
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0, float(w), float(h)


def analyze_scene(frames, frame_w, min_coexistence=MIN_COEXISTENCE):
    """¿Estos cuadros muestreados muestran un dos-shot apilable? →
    ((cx, cy, w, h) izquierda, derecha) o None."""
    if not frames:
        return None
    # Público o grupo (3+ rostros grandes en la mayoría de cuadros): no es un
    # dos-shot; apilar a dos desconocidos se ve como un error (cambio de ClipAI).
    crowd = [len([c for c in dedupe_faces(f) if c['box'][2] >= MIN_FACE_WIDTH * frame_w]) >= 3 for f in frames]
    if sum(crowd) > len(frames) / 2:
        return None
    lefts, rights = [], []
    for candidates in frames:
        pair = _two_largest(candidates, frame_w)
        if not pair:
            continue
        lc, rc = _centre(pair[0]['box']), _centre(pair[1]['box'])
        if (rc[0] - lc[0]) < MIN_SEPARATION * frame_w:
            continue
        lefts.append(lc)
        rights.append(rc)
    if len(lefts) < min_coexistence * len(frames):
        return None
    # Mediana: un cuadro con un espontáneo no arrastra el recorte de la escena.
    left = tuple(float(np.median([c[i] for c in lefts])) for i in range(4))
    right = tuple(float(np.median([c[i] for c in rights])) for i in range(4))
    return left, right


def split_geometry(orig_w, orig_h, out_w, out_h, centre):
    """Recorte (x, y, w, h) que encuadra ``centre`` en una mitad de la pila."""
    half_h = out_h // 2
    half_h -= half_h % 2
    aspect = out_w / float(half_h)
    crop_h = int(round(orig_h * max(0.3, min(split_tightness(), 1.0))))
    crop_w = int(round(crop_h * aspect))
    if crop_w > orig_w:
        crop_w = orig_w
        crop_h = int(round(crop_w / aspect))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    x = max(0, min(int(round(centre[0] - crop_w / 2.0)), orig_w - crop_w))
    # Los rostros van altos en el cuadro: margen de cabeza natural.
    y = max(0, min(int(round(centre[1] - crop_h * 0.42)), orig_h - crop_h))
    return x - (x % 2), y - (y % 2), crop_w, crop_h, half_h


def read_at(cap, indices, max_forward=300):
    """Cuadros en esos índices con una pasada hacia delante (sin buscar por cada
    muestra, que en H.264 decodifica el mismo GOP una y otra vez)."""
    import cv2
    pos, last = 0, (None, None)
    for idx in indices:
        idx = int(idx)
        if idx == last[0]:
            yield last[1]
            continue
        if idx < pos or idx - pos > max_forward:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            pos = idx
        frame = None
        while pos < idx:
            if not cap.grab():
                break
            pos += 1
        if pos == idx:
            ok, frame = cap.read()
            pos += 1
            if not ok:
                frame = None
        last = (idx, frame)
        yield frame


def detect_split_scenes(video_path, scene_bounds, fps, scene_indices, detect_faces,
                        min_coexistence=MIN_COEXISTENCE):
    """{índice_escena: (centro_izq, centro_der)} para las escenas apilables."""
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {}
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    plan = []
    for i in scene_indices:
        s_f, e_f = scene_bounds[i]
        if (e_f - s_f) / fps < MIN_SCENE_SECONDS:
            continue
        n = int(min(max((e_f - s_f) / fps / SECONDS_PER_SAMPLE, MIN_SAMPLES), MAX_SAMPLES))
        last_f = min(e_f - 1, total - 1) if total else e_f - 1
        if last_f < s_f:
            continue
        plan.append((i, n, [int(round(f)) for f in np.linspace(s_f, last_f, n)]))
    found = {}
    try:
        frames = read_at(cap, [f for _i, _n, idxs in plan for f in idxs])
        for i, n, idxs in plan:
            sampled = []
            for _ in idxs:
                frame = next(frames)
                if frame is None or frame.mean() < 16:  # fundido a negro
                    continue
                sampled.append(detect_faces(frame))
            if len(sampled) < max(4, n // 2):
                continue
            pair = analyze_scene(sampled, frame_w, min_coexistence)
            if pair:
                found[i] = pair
    finally:
        cap.release()
    return found


def compose_split(frame, top_geo, bottom_geo, out_w, out_h, resize):
    tx, ty, tw, th, half_h = top_geo
    bx, by, bw, bh, _ = bottom_geo
    top = resize(frame[ty:ty + th, tx:tx + tw], out_w, half_h)
    bot = resize(frame[by:by + bh, bx:bx + bw], out_w, half_h)
    out = np.vstack([top, bot])
    if out.shape[0] < out_h:
        out = np.vstack([out, np.zeros((out_h - out.shape[0], out_w, 3), dtype=out.dtype)])
    return out


# ── Hablante activo ────────────────────────────────────────

WINDOW_SECONDS = 0.4
AUDIO_FLOOR = 0.18
MIN_MARGIN = 0.15
ANALYSIS_WIDTH = 480


def mouth_region(box, frame_w, frame_h, scale=1.0):
    x, y, w, h = [v / scale for v in box]
    cx, mouth_y = x + w / 2.0, y + h * 0.72
    half_w, half_h = w * 0.36, h * 0.22
    x0 = int(max(0, min(cx - half_w, frame_w - 1)))
    x1 = int(max(x0 + 1, min(cx + half_w, frame_w)))
    y0 = int(max(0, min(mouth_y - half_h, frame_h - 1)))
    y1 = int(max(y0 + 1, min(mouth_y + half_h, frame_h)))
    return x0, y0, x1, y1


def audio_envelope(video_path, start_s, duration_s, window_s=WINDOW_SECONDS):
    try:
        raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{start_s:.4f}", "-t", f"{duration_s:.4f}",
                              "-i", str(video_path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    samples = np.frombuffer(raw or b"", dtype=np.int16).astype(np.float32)
    per = max(1, int(8000 * window_s))
    n = len(samples) // per
    if n < 1:
        return []
    rms = np.sqrt(np.mean(samples[:n * per].reshape(n, per) ** 2, axis=1))
    peak = rms.max()
    return (rms / peak).tolist() if peak > 0 else [0.0] * n


def normalise_activity(activity):
    """Cada boca en su propio rango de reposo a actividad (luz/contraste)."""
    if not activity:
        return []
    cols = np.asarray(activity, dtype=float)
    if cols.ndim != 2 or cols.shape[1] < 2:
        return activity
    low, high = np.percentile(cols, 20, axis=0), np.percentile(cols, 80, axis=0)
    spread = np.where(high - low > 1e-6, high - low, 1.0)
    return np.clip((cols - low) / spread, 0.0, None).tolist()


def attribute_windows(activity, loudness, min_margin=MIN_MARGIN):
    verdicts = []
    for i, (a, b) in enumerate(activity):
        if loudness and i < len(loudness) and loudness[i] < AUDIO_FLOOR:
            verdicts.append(None)
            continue
        total = a + b
        if total <= 0:
            verdicts.append(None)
            continue
        verdicts.append(None if abs(a - b) / total < min_margin else (0 if a > b else 1))
    return verdicts


def hold(verdicts, min_windows=3):
    """Suaviza: un «sí» suelto no roba el plano; hace falta sostenerlo."""
    out, current, pending, run = [], None, None, 0
    for v in verdicts:
        if v is None or v == current:
            if v == current:
                pending, run = None, 0
            out.append(current)
            continue
        if v == pending:
            run += 1
        else:
            pending, run = v, 1
        if current is None or run >= min_windows:
            current, pending, run = v, None, 0
        out.append(current)
    if all(v is None for v in out):
        return out
    first = next(v for v in out if v is not None)
    return [first if v is None else v for v in out]


class _MouthMeter:
    """Actividad de boca por ventana para las escenas SPLIT (pase de rastreo)."""

    def __init__(self, splits, frame_w, frame_h, fps):
        import cv2
        self.cv2 = cv2
        self.small_w = min(ANALYSIS_WIDTH, frame_w) - min(ANALYSIS_WIDTH, frame_w) % 2
        self.small_h = max(2, int(frame_h * self.small_w / frame_w))
        scale = frame_w / float(self.small_w)
        self.regions = {sid: [mouth_region(_box(c), self.small_w, self.small_h, scale) for c in pair]
                        for sid, pair in splits.items()}
        self.per_window = max(1, int(round(fps * WINDOW_SECONDS)))
        self.activity = {sid: [] for sid in splits}
        self._bucket, self._prev, self._sid, self._count = [], None, None, 0

    def __call__(self, n, frame, sid):
        if sid != self._sid:
            self._flush()
            self._sid, self._prev, self._bucket, self._count = sid, None, [], 0
        gray = self.cv2.cvtColor(self.cv2.resize(frame, (self.small_w, self.small_h)), self.cv2.COLOR_BGR2GRAY)
        if self._prev is not None:
            self._bucket.append([float(np.mean(np.abs(gray[y0:y1, x0:x1].astype(np.int16)
                                                      - self._prev[y0:y1, x0:x1].astype(np.int16))))
                                 for x0, y0, x1, y1 in self.regions[sid]])
        self._prev = gray
        self._count += 1
        if self._count % self.per_window == 0:
            self._flush()

    def _flush(self):
        if self._sid is not None and self._bucket:
            self.activity[self._sid].append(np.mean(self._bucket, axis=0).tolist())
        self._bucket = []


def _box(centre):
    cx, cy, w, h = centre
    return [cx - w / 2.0, cy - h / 2.0, w, h]


# ── API ──────────────────────────────────────────────────────────────────────

def _merge_ranges(ranges):
    out = []
    for r in ranges:
        if out and out[-1]["layout"] == r["layout"] and abs(out[-1]["end"] - r["start"]) < 1e-3:
            out[-1]["end"] = r["end"]
        else:
            out.append(dict(r))
    return out


def reframe(source_slice: Path, output: Path, mode: str = "auto", *, width: int = 1080,
            height: int = 1920, on_progress=None, cancelled=None) -> ReframeResult:
    """mode: auto | track | split | wide | off.

    Llama al render de reencuadre (análisis por escena + cámara quieta) y añade
    el diseño SPLIT cuando hay dos rostros. Escribe
    ``output`` (H.264 ``width``×``height`` con el audio original) y su sidecar
    ``<output>.layout.json``.

    ``on_progress(0..1)`` recibe el avance (rastreo = primera mitad, dibujo =
    segunda) y ``cancelled()`` se consulta en cada cuadro: si devuelve True se
    lanza StopRequested y no se escribe ``output``.
    """
    from media.errors import StopRequested
    from media.vendor.reframe import reframe as cr
    from media.vendor.reframe.reframe_detect import detect_face_candidates

    mode = mode if mode in MODES else "auto"
    output = Path(output)
    work = output.parent
    tmp_cfr, tmp_video = work / "_reframe_cfr.mp4", work / "_reframe_video.mp4"
    ff, fp = ffmpeg_bin(), ffprobe_bin()
    try:
        src = cr.normalize_vfr(str(source_slice), str(tmp_cfr), ff, fp, video_args(faststart=False))
        bounds, fps, total = cr.scene_list(src)
        cam, src_w, src_h = cr.make_cameraman(src, width, height)

        if mode == "off":
            layouts = ["GENERAL"] * len(bounds)
        else:
            layouts = cr.analyze_scenes_strategy(src, bounds, reader=read_at)
            if mode == "track":  # una persona: fija, o siguiéndola si camina
                layouts = ["TRACK" if s not in ("GENERAL", "FOLLOW") else s for s in layouts]
            elif mode == "wide":
                layouts = ["WIDE" if s != "GENERAL" else s for s in layouts]
        splits = {}
        if mode == "split" or (mode == "auto" and split_enabled()):
            candidates = [i for i, s in enumerate(layouts) if s == "WIDE" or (mode == "split" and s == "TRACK")]
            splits = detect_split_scenes(src, bounds, fps, candidates, detect_face_candidates,
                                         min_coexistence=0.25 if mode == "split" else MIN_COEXISTENCE)
            for i in splits:
                layouts[i] = "SPLIT"

        state = {"last": -1.0}

        def report(frac: float) -> None:
            if cancelled is not None and cancelled():
                raise StopRequested("render cancelado")
            if on_progress is not None and frac - state["last"] >= 0.01:
                state["last"] = frac
                on_progress(frac)

        frames_total = max(1, int(total or 0))
        meter = _MouthMeter(splits, src_w, src_h, fps) if (splits and speaker_cut_enabled()) else None
        targets, scene_ids = cr.track_static_targets(
            src, bounds, layouts, cam, frame_hook=meter, hook_scenes=frozenset(splits) if meter else frozenset(),
            tick=lambda n: report(0.5 * min(1.0, n / frames_total)))

        # Hablante activo: en vez de apilar, corte en seco a quien habla.
        speaker_frames: dict[int, list] = {}
        if meter is not None:
            meter._flush()
            for sid, act in meter.activity.items():
                s_f, e_f = bounds[sid]
                loud = audio_envelope(src, s_f / fps, (e_f - s_f) / fps)
                held = hold(attribute_windows(normalise_activity(act), loud))
                if any(v is not None for v in held):
                    speaker_frames[sid] = held
                    layouts[sid] = "SPEAKER"

        geos = {sid: (split_geometry(src_w, src_h, width, height, pair[0]),
                      split_geometry(src_w, src_h, width, height, pair[1])) for sid, pair in splits.items()}
        per_window = max(1, int(round(fps * WINDOW_SECONDS)))

        def frame_fn(n, frame):
            sid = scene_ids[n] if n < len(scene_ids) else (scene_ids[-1] if scene_ids else 0)
            layout = layouts[sid]
            if layout == "SPLIT":
                return compose_split(frame, *geos[sid], width, height, cr.resize_to_output)
            if layout == "SPEAKER":
                s_f = bounds[sid][0]
                held = speaker_frames[sid]
                who = held[min((n - s_f) // per_window, len(held) - 1)] or 0
                cx, cy, _w, fh = splits[sid][who]
                box = cam.crop_box_at(cx, cy, min(1.35, max(1.0, cam.max_crop_height * 0.4 / max(fh, 1))))
                return cr.crop_frame(frame, box, width, height)
            tgt = targets[n] if n < len(targets) else None
            if layout == "GENERAL" or tgt is None:
                return cr.create_general_frame(frame, width, height)
            return cr.crop_frame(frame, cam.crop_box_at(*tgt), width, height)

        proc = cr.open_encoder(width, height, fps, str(tmp_video), ff, video_args(faststart=False))
        lower_priority(proc)  # el estudio no se traba mientras se codifica
        written = {"n": 0}

        def write(out) -> None:
            # Fuera de frame_fn: allí las excepciones se tragan (cuadro corrupto).
            written["n"] += 1
            report(0.5 + 0.5 * min(1.0, written["n"] / frames_total))
            proc.stdin.write(out.tobytes())

        try:
            frames, dropped = cr.render_frames(src, frame_fn, write)
            proc.stdin.close()
            err = proc.stderr.read().decode(errors="replace")
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if proc.returncode != 0 or frames == 0:
            raise RuntimeError(f"reencuadre: el codificador falló ({err[-400:]})")
        if dropped:
            log.warning("reencuadre: %d/%d cuadros duplicados por error", dropped, frames)
        cr.mux_audio(src, str(tmp_video), str(output), ff, fp)

        end_s = frames / fps
        scenes, ranges = [], []
        for sid, (s_f, e_f) in enumerate(bounds):
            start, end = s_f / fps, min(e_f / fps, end_s)
            if end <= start:
                continue
            layout = layouts[sid]
            label = {"SPEAKER": "track", "FOLLOW": "track"}.get(layout, layout.lower())
            ranges.append({"start": start, "end": end, "layout": label})
            info = {"start": round(start, 3), "end": round(end, 3), "layout": label}
            if layout == "SPLIT":
                info["split"] = {"top": list(geos[sid][0][:4]), "bottom": list(geos[sid][1][:4])}
            elif layout in ("TRACK", "WIDE", "FOLLOW"):
                idx = min(s_f, len(targets) - 1)
                if 0 <= idx < len(targets) and targets[idx]:
                    info["crop"] = list(cam.crop_box_at(*targets[idx]))  # FOLLOW: el del primer cuadro
                if layout == "FOLLOW":
                    info["follow"] = True
            elif layout == "SPEAKER":
                info["speaker_cut"] = True
            scenes.append(info)
        ranges = layout_ranges.write(output, _merge_ranges(ranges))
        write_json(output.with_name("crop.json"), {"mode": mode, "fps": fps, "source_size": [src_w, src_h],
                                                    "output_size": [width, height], "scenes": scenes})
        return ReframeResult(output=output, layout_ranges=ranges, scenes=scenes)
    finally:
        for f in (tmp_cfr, tmp_video):
            try:
                f.unlink()
            except OSError:
                pass


def best_cover_time(video: Path, max_samples: int = 48) -> float | None:
    """Segundo del mejor cuadro de ``video`` para una portada (misma
    puntuación que `pick_cover`: rostro + nitidez + exposición). None si falla."""
    from media.vendor.reframe import reframe as cr
    try:
        t, _frame = cr.best_cover_frame(str(video), reader=read_at, max_samples=max_samples)
        return t
    except Exception as exc:
        log.warning("cuadro de portada: %s", exc)
        return None


def pick_cover(video: Path, out_jpg: Path) -> Path | None:
    """Portada automática: rostro + nitidez + exposición."""
    from media.vendor.reframe import reframe as cr
    try:
        return cr.select_cover_frame(str(video), str(out_jpg), reader=read_at) and Path(out_jpg)
    except Exception as exc:
        log.warning("portada: %s", exc)
        return None
