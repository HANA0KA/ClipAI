"""ffprobe + ayudas puras de sincronía A/V (VFR, start_time, fps).

Copiado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/media_probe.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: binario de ffprobe como parámetro; solo las funciones que usa el
reencuadre (los silencios viven en media/services/cut_ops.py).
"""
from __future__ import annotations

import subprocess


def parse_frame_rate(rate: str) -> float:
    """"30000/1001" | "25" | "0/0" → fps (0.0 si no se puede leer)."""
    if not rate:
        return 0.0
    rate = rate.strip()
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return 0.0 if den_f == 0 else float(num) / den_f
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return 0.0


def is_vfr(r_frame_rate: str, avg_frame_rate: str, threshold: float = 0.5) -> bool:
    """True si la tasa nominal y la media difieren lo suficiente (VFR)."""
    r = parse_frame_rate(r_frame_rate)
    avg = parse_frame_rate(avg_frame_rate)
    if r <= 0 or avg <= 0:
        return False
    return abs(r - avg) > threshold


def parse_start_time(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.strip())
    except ValueError:
        return 0.0


def audio_sync_seek_args(video_start_time: float, min_offset: float = 0.05) -> list[str]:
    """Recorta del audio el adelanto igual al start_time del video (YouTube
    suele traer audio en 0,0 s y video en 1,8 s)."""
    if video_start_time is None or video_start_time <= min_offset:
        return []
    return ["-ss", f"{video_start_time:.3f}"]


def reconcile_fps(reader_fps: float, scene_fps: float, tol: float = 0.1) -> float:
    """La tasa del codificador debe ser la del lector de OpenCV (quien entrega
    los cuadros); si difiere de la del detector de escenas, gana el lector."""
    if reader_fps is None or reader_fps <= 0:
        return scene_fps
    if scene_fps is None or scene_fps <= 0:
        return reader_fps
    if abs(reader_fps - scene_fps) > tol:
        return reader_fps
    return scene_fps


def probe_stream_start_time(video_path: str, stream: str = "v:0", ffprobe: str = "ffprobe") -> float:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", stream,
             "-show_entries", "stream=start_time", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return parse_start_time(result.stdout)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    return 0.0


def probe_is_variable_frame_rate(video_path: str, threshold: float = 0.5, ffprobe: str = "ffprobe") -> bool:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate,avg_frame_rate", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return False
        parts = result.stdout.strip().split(",")
        return len(parts) >= 2 and is_vfr(parts[0], parts[1], threshold=threshold)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
