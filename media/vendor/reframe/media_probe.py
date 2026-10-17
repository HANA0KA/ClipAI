"""Lecturas de ffprobe y ayudas de sincronía audio/video (VFR, start_time, fps)."""
from __future__ import annotations

import json
import subprocess

_PROBE_TIMEOUT_S = 15


def _stream_info(video_path: str, entries: str, ffprobe: str, stream: str = "v:0") -> dict | None:
    """Campos pedidos del primer flujo de ``stream``, o None si ffprobe falla."""
    cmd = [ffprobe, "-v", "error", "-select_streams", stream,
           "-show_entries", f"stream={entries}", "-of", "json", str(video_path)]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S)
        if done.returncode != 0:
            return None
        streams = json.loads(done.stdout or "{}").get("streams") or []
        return streams[0] if streams else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def parse_frame_rate(rate: str) -> float:
    """Fracción de ffprobe («30000/1001», «25», «0/0») a fps; 0.0 si no es válida."""
    text = (rate or "").strip()
    if not text:
        return 0.0
    try:
        numerator, _, denominator = text.partition("/")
        if not denominator:
            return float(numerator)
        divisor = float(denominator)
        return float(numerator) / divisor if divisor else 0.0
    except ValueError:
        return 0.0


def probe_is_variable_frame_rate(video_path: str, threshold: float = 0.5, ffprobe: str = "ffprobe") -> bool:
    """True si la tasa nominal y la media del video difieren más que ``threshold`` fps."""
    info = _stream_info(video_path, "r_frame_rate,avg_frame_rate", ffprobe)
    if not info:
        return False
    nominal = parse_frame_rate(info.get("r_frame_rate", ""))
    average = parse_frame_rate(info.get("avg_frame_rate", ""))
    return nominal > 0 and average > 0 and abs(nominal - average) > threshold


def probe_stream_start_time(video_path: str, stream: str = "v:0", ffprobe: str = "ffprobe") -> float:
    """Segundo en que empieza el flujo (0.0 si no se puede leer)."""
    info = _stream_info(video_path, "start_time", ffprobe, stream)
    try:
        return float((info or {}).get("start_time") or 0.0)
    except ValueError:
        return 0.0


def audio_sync_seek_args(video_start_time: float, min_offset: float = 0.05) -> list[str]:
    """``-ss`` que quita del audio el adelanto del video (YouTube suele traer el
    audio en 0,0 s y el video en 1,8 s)."""
    if video_start_time is None or video_start_time <= min_offset:
        return []
    return ["-ss", f"{video_start_time:.3f}"]


def reconcile_fps(reader_fps: float, scene_fps: float, tol: float = 0.1) -> float:
    """fps para codificar: manda el lector de OpenCV (quien entrega los cuadros)
    cuando discrepa del detector de escenas por más de ``tol``."""
    if not reader_fps or reader_fps <= 0:
        return scene_fps
    if not scene_fps or scene_fps <= 0:
        return reader_fps
    return reader_fps if abs(reader_fps - scene_fps) > tol else scene_fps
