"""Miniaturas y forma de onda para la línea de tiempo del estudio de edición.

Para un rango [a, b] del video fuente devuelve una tira JPG con N miniaturas
(una cada ``interval`` s) y ~600 picos de audio normalizados, leídos de
audio.wav (16 kHz mono). Todo queda en caché en la carpeta del clip.
"""
from __future__ import annotations

import math
import os
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from media.services.atomic import read_json, write_json
from media.services.ffmpeg import ffmpeg_bin

THUMB_W, THUMB_H = 160, 90
MAX_THUMBS = 48
PEAKS = 600
THUMB_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))


def plan_range(start: float, end: float, duration: float) -> tuple[int, int, int, float]:
    """Rango redondeado (para que la caché se reutilice) y cuántas miniaturas."""
    a = max(0, int(math.floor(start / 5.0) * 5))
    b = int(math.ceil(end / 5.0) * 5)
    if duration > 0:
        b = min(b, int(math.ceil(duration)))
    b = max(b, a + 1)
    n = max(6, min(MAX_THUMBS, int(math.ceil((b - a) / 2.5))))
    return a, b, n, (b - a) / n


def peaks(wav_path: Path, a: float, b: float, count: int = PEAKS) -> list[float]:
    """Pico absoluto por tramo, normalizado a 0..1 con el percentil 99."""
    import numpy as np
    with wave.open(str(wav_path), "rb") as wf:
        sr, total = wf.getframerate(), wf.getnframes()
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            return []
        s0 = max(0, min(total, int(a * sr)))
        s1 = max(s0, min(total, int(b * sr)))
        wf.setpos(s0)
        raw = wf.readframes(s1 - s0)
    y = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32))
    if y.size == 0:
        return [0.0] * count
    edges = np.linspace(0, y.size, count + 1).astype(int)
    vals = np.array([y[edges[i]:max(edges[i] + 1, edges[i + 1])].max() if edges[i] < y.size else 0.0
                     for i in range(count)])
    ref = float(np.percentile(vals, 99)) or 1.0
    return [round(float(min(1.0, v / ref)), 3) for v in vals]


def _thumb(source: Path, t: float) -> bytes:
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-threads", "1", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(source), "-an", "-sn", "-dn", "-threads", "1", "-frames:v", "1", "-vf", f"scale={THUMB_W}:{THUMB_H}:force_original_aspect_ratio=increase,"
         f"crop={THUMB_W}:{THUMB_H}", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5", "-"],
        capture_output=True, timeout=60)
    return proc.stdout if proc.returncode == 0 else b""


def build(project_folder: Path, clip_folder: Path, start: float, end: float, duration: float) -> dict:
    """{"start", "end", "count", "interval", "thumbs" (ruta relativa a la
    carpeta del clip), "thumbW", "thumbH", "peaks"}."""
    import io

    from PIL import Image

    a, b, n, interval = plan_range(start, end, duration)
    out_dir = clip_folder / "timeline"
    meta_path = out_dir / f"{a}-{b}.json"
    cached = read_json(meta_path)
    if cached and (out_dir / cached["thumbs"]).exists():
        return {**cached, "thumbs": f"timeline/{cached['thumbs']}"}
    source = project_folder / "source.mp4"
    out_dir.mkdir(parents=True, exist_ok=True)
    times = [a + (i + 0.5) * interval for i in range(n)]
    # Pocos ffmpeg de un hilo cada uno: la tira no acapara la CPU mientras
    # editas (antes, 6 procesos × todos los núcleos a la vez).
    with ThreadPoolExecutor(max_workers=THUMB_WORKERS) as pool:
        frames = list(pool.map(lambda t: _thumb(source, t), times))
    sprite = Image.new("RGB", (THUMB_W * n, THUMB_H), (20, 22, 28))
    for i, data in enumerate(frames):
        if data:
            try:
                sprite.paste(Image.open(io.BytesIO(data)).convert("RGB"), (i * THUMB_W, 0))
            except Exception:
                pass
    name = f"{a}-{b}.jpg"
    tmp = out_dir / f".{name}.tmp.jpg"
    sprite.save(tmp, "JPEG", quality=72)
    tmp.replace(out_dir / name)
    wav = project_folder / "audio.wav"
    meta = {"start": a, "end": b, "count": n, "interval": round(interval, 4), "thumbs": name,
            "thumbW": THUMB_W, "thumbH": THUMB_H, "peaks": peaks(wav, a, b) if wav.exists() else []}
    write_json(meta_path, meta)
    return {**meta, "thumbs": f"timeline/{name}"}


__all__ = ["build", "plan_range", "peaks"]
