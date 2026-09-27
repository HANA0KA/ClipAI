"""Revisión de calidad del render antes de entregarlo (plan 6.6.7).

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Rutas originales: src/clippyme/pipeline/media_qa.py (probe_media,
inspect_signal, inspect_clip) y src/clippyme/domain/clip_qa.py
(evaluate_clip_qa y sus umbrales).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: un solo módulo, binarios ffmpeg/ffprobe parametrizables, medida de
loudness integrada (ebur128) para comprobar los −14 LUFS, sin Smart Cut.

Los defectos estructurales (sin video/audio, duración o proporción mal) son
críticos: el render se repite una vez. Los de señal (negro, congelado, audio
bajo) son avisos que se guardan en el clip sin borrarlo.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

DURATION_SHORT_RATIO = 0.25
DURATION_LONG_SLACK = 1.5
MIN_BYTES = 10_000
ASPECT_TOLERANCE = 0.08
BLACK_WARNING_RATIO = 0.45
FREEZE_WARNING_RATIO = 0.70
QUIET_WARNING_DB = -38.0
CLIP_WARNING_DB = -0.1
LUFS_TOLERANCE = 3.0

_BLACK_RE = re.compile(r"black_duration:([0-9.]+)")
_FREEZE_RE = re.compile(r"freeze_duration:\s*([0-9.]+)")
_MEAN_RE = re.compile(r"mean_volume:\s*(-?(?:inf|[0-9.]+))\s*dB", re.IGNORECASE)
_MAX_RE = re.compile(r"max_volume:\s*(-?(?:inf|[0-9.]+))\s*dB", re.IGNORECASE)
_LUFS_RE = re.compile(r"I:\s*(-?[0-9.]+)\s*LUFS")


def _float(value: Any) -> float | None:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def probe_media(path: str, ffprobe: str = "ffprobe", timeout: float = 25.0) -> dict[str, Any]:
    report: dict[str, Any] = {"exists": os.path.isfile(path), "size_bytes": None, "duration": None,
                              "has_video": False, "has_audio": False, "width": None, "height": None,
                              "video_codec": None, "audio_codec": None, "fps": None, "probe_error": None}
    try:
        report["size_bytes"] = os.path.getsize(path)
    except OSError as exc:
        report["probe_error"] = str(exc)
        return report
    try:
        proc = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                              capture_output=True, text=True, timeout=timeout)
        payload = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
        if proc.returncode != 0:
            report["probe_error"] = (proc.stderr or "ffprobe failed")[-500:]
            return report
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        report["probe_error"] = str(exc)
        return report
    report["duration"] = _float((payload.get("format") or {}).get("duration"))
    for st in payload.get("streams") or []:
        if st.get("codec_type") == "video" and not report["has_video"]:
            report.update(has_video=True, width=int(st.get("width") or 0) or None,
                          height=int(st.get("height") or 0) or None, video_codec=st.get("codec_name"))
            rate = str(st.get("avg_frame_rate") or "")
            if "/" in rate:
                n, d = rate.split("/", 1)
                if _float(d):
                    report["fps"] = round(float(n) / float(d), 3)
        elif st.get("codec_type") == "audio" and not report["has_audio"]:
            report.update(has_audio=True, audio_codec=st.get("codec_name"))
    return report


def inspect_signal(path: str, duration: float | None, ffmpeg: str = "ffmpeg",
                   timeout: float = 180.0) -> dict[str, Any]:
    """Negro, congelado, volumen y loudness integrada en una pasada."""
    m: dict[str, Any] = {"black_ratio": None, "freeze_ratio": None, "mean_volume_db": None,
                         "max_volume_db": None, "integrated_lufs": None, "signal_error": None}
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", path,
           "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-60dB:d=2",
           "-af", "volumedetect,ebur128", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        m["signal_error"] = str(exc)
        return m
    text = proc.stderr or ""
    if duration and duration > 0:
        black = sum(float(v) for v in _BLACK_RE.findall(text))
        freeze = sum(float(v) for v in _FREEZE_RE.findall(text))
        m["black_ratio"] = round(min(1.0, black / duration), 4)
        m["freeze_ratio"] = round(min(1.0, freeze / duration), 4)
    mm = _MEAN_RE.search(text)
    if mm and mm.group(1).lower() != "-inf":
        m["mean_volume_db"] = _float(mm.group(1))
    mx = _MAX_RE.search(text)
    if mx and mx.group(1).lower() != "-inf":
        m["max_volume_db"] = _float(mx.group(1))
    lufs = _LUFS_RE.findall(text)
    if lufs:
        m["integrated_lufs"] = _float(lufs[-1])  # el resumen final va al último
    if proc.returncode != 0:
        m["signal_error"] = text[-500:]
    return m


def evaluate_clip_qa(*, actual_duration, expected_duration, has_audio, has_video, size_bytes,
                     width=None, height=None, expected_aspect=None, black_ratio=None,
                     freeze_ratio=None, mean_volume_db=None, max_volume_db=None,
                     integrated_lufs=None, target_lufs=None, smartcut_applied=False) -> dict:
    issues: list[str] = []
    warnings: list[str] = []
    if size_bytes is not None and size_bytes < MIN_BYTES:
        issues.append(f"archivo casi vacío ({size_bytes} bytes)")
    if not has_video:
        issues.append("sin pista de video")
    if not has_audio:
        issues.append("sin pista de audio")
    if actual_duration is not None and actual_duration <= 0:
        issues.append("duración cero")
    if actual_duration and expected_duration and expected_duration > 0:
        ratio = actual_duration / expected_duration
        if ratio > DURATION_LONG_SLACK:
            issues.append(f"dura {actual_duration:.1f}s, mucho más de lo esperado ({expected_duration:.1f}s)")
        if ratio < DURATION_SHORT_RATIO and not smartcut_applied:
            issues.append(f"dura {actual_duration:.1f}s, mucho menos de lo esperado ({expected_duration:.1f}s)")
    if width and height and expected_aspect:
        aspect = width / height
        if abs(aspect - expected_aspect) / expected_aspect > ASPECT_TOLERANCE:
            issues.append(f"proporción incorrecta ({width}x{height})")
    if black_ratio is not None and black_ratio > BLACK_WARNING_RATIO:
        warnings.append(f"mucho cuadro negro ({black_ratio * 100:.0f} %)")
    if freeze_ratio is not None and freeze_ratio > FREEZE_WARNING_RATIO:
        warnings.append(f"video congelado gran parte del tiempo ({freeze_ratio * 100:.0f} %)")
    if mean_volume_db is not None and mean_volume_db < QUIET_WARNING_DB:
        warnings.append(f"audio muy bajo (media {mean_volume_db:.1f} dB)")
    if max_volume_db is not None and max_volume_db > CLIP_WARNING_DB:
        warnings.append(f"el audio puede saturar (pico {max_volume_db:.2f} dB)")
    if integrated_lufs is not None and target_lufs is not None \
            and abs(integrated_lufs - target_lufs) > LUFS_TOLERANCE:
        warnings.append(f"loudness {integrated_lufs:.1f} LUFS (objetivo {target_lufs:.0f})")
    return {"ok": not issues and not warnings, "critical": bool(issues), "issues": issues, "warnings": warnings}


def inspect_clip(path: str, *, expected_duration: float | None, expected_aspect: float | None,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", target_lufs: float | None = None,
                 smartcut_applied: bool = False) -> dict:
    probe = probe_media(path, ffprobe)
    signal = inspect_signal(path, probe.get("duration"), ffmpeg) if probe.get("has_video") else {}
    verdict = evaluate_clip_qa(
        actual_duration=probe.get("duration"), expected_duration=expected_duration,
        has_audio=bool(probe.get("has_audio")), has_video=bool(probe.get("has_video")),
        size_bytes=probe.get("size_bytes"), width=probe.get("width"), height=probe.get("height"),
        expected_aspect=expected_aspect, black_ratio=signal.get("black_ratio"),
        freeze_ratio=signal.get("freeze_ratio"), mean_volume_db=signal.get("mean_volume_db"),
        max_volume_db=signal.get("max_volume_db"), integrated_lufs=signal.get("integrated_lufs"),
        target_lufs=target_lufs, smartcut_applied=smartcut_applied)
    return {**verdict, "metrics": {**probe, **signal}}
