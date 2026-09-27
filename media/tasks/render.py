"""Tarea `render` (plan 6.4–6.6): clip final 1080×1920 listo para subir.

Orden de capas: recorte 16:9 → reencuadre → subtítulos → corte inteligente
(opcional) → gancho → audio. El trozo 16:9 (`source.mp4` del clip) y el
reencuadre (`reframed.mp4`) quedan en caché: cambiar plantilla, palabras o
gancho solo repite la última pasada; cambiar de diseño re-renderiza desde el
trozo guardado. Todas las pasadas usan el mismo CRF (services/ffmpeg.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from media.config import FONTS_DIR, settings
from media.errors import PermanentError
from media.services import ass_builder, db, layout_ranges, media_qa, reframe_adapter, smartcut
from media.services.atomic import read_json, write_json
from media.services.cut_ops import detect_silences
from media.services.ffmpeg import ffmpeg_bin, ffprobe_bin, has_libass, run, video_args
from media.tasks.common import clip_folder, log, project_folder

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30


def _rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(settings().data_dir.resolve()))


def slice_plan(clip: dict) -> list[tuple[float, float]]:
    """Tramos del video fuente que forman el clip, en orden."""
    parts = []
    if clip.get("prependBestLine") and clip.get("bestLineStart") is not None and clip.get("bestLineEnd"):
        parts.append((float(clip["bestLineStart"]), float(clip["bestLineEnd"])))
    parts.append((float(clip["startSec"]), float(clip["endSec"])))
    return parts


def clip_words(captions: dict, parts: list[tuple[float, float]]) -> list[dict]:
    """Palabras absolutas de captions.json → línea de tiempo del clip."""
    out, offset = [], 0.0
    for a, b in parts:
        for w in captions.get("words") or []:
            mid = (w["start"] + w["end"]) / 2
            if a <= mid < b and str(w.get("w", "")).strip():
                out.append({"w": w["w"], "start": round(max(0.0, w["start"] - a) + offset, 3),
                            "end": round(min(b, w["end"]) - a + offset, 3)})
        offset += b - a
    return out


def cut_slice(source: Path, parts: list[tuple[float, float]], dest: Path) -> None:
    """Trozo 16:9 del clip (CFR, H.264, AAC). Con dos tramos se concatenan."""
    ff = ffmpeg_bin()
    tmp = dest.with_name("source.tmp.mp4")
    args = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    for a, b in parts:
        args += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(source)]
    if len(parts) == 1:
        args += ["-map", "0:v:0", "-map", "0:a:0"]
    else:
        streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(parts)))
        args += ["-filter_complex", f"{streams}concat=n={len(parts)}:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]
    args += [*video_args(faststart=False), "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k", str(tmp)]
    run(args, what="recortar el trozo 16:9")
    tmp.replace(dest)


def _final_command(cfolder: Path, reframed: Path, out: Path, *, ass_main: str, ass_hook: str | None,
                   keep: list[tuple[float, float]] | None, zoom: float | None, duration: float) -> list[str]:
    fonts = os.path.relpath(FONTS_DIR, cfolder)
    v = []
    if zoom and zoom > 1.0:
        frames = max(1, int(duration * OUT_FPS))
        v.append(f"fps={OUT_FPS},zoompan=z='1+{(zoom - 1) / frames:.8f}*on':x='iw/2-(iw/zoom/2)'"
                 f":y='ih/2-(ih/zoom/2)':d=1:s={OUT_W}x{OUT_H}:fps={OUT_FPS}")
    v.append(f"ass={ass_main}:fontsdir={fonts}")
    a = []
    if keep:
        v.append(smartcut.video_filter(keep))
        a.append(smartcut.audio_filter(keep))
    if ass_hook:
        v.append(f"ass={ass_hook}:fontsdir={fonts}")
    v += [f"fps={OUT_FPS}", "format=yuv420p"]
    lufs = settings().target_lufs
    a += [f"loudnorm=I={lufs:g}:TP=-1.5:LRA=11", "aresample=48000"]
    graph = f"[0:v]{','.join(v)}[v];[0:a]{','.join(a)}[a]"
    return [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(reframed),
            "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
            *video_args(faststart=True), "-r", str(OUT_FPS), "-c:a", "aac", "-b:a", "192k", str(out)]


def render_clip(clip: dict) -> dict:
    s = settings()
    project = db.get_project(clip["projectId"])
    if project is None:
        raise PermanentError("El proyecto ya no existe.")
    folder = project_folder(project["id"])
    cfolder = clip_folder(project["id"], clip["id"])
    source = folder / "source.mp4"

    # 1 · Trozo 16:9 (caché por bordes)
    parts = slice_plan(clip)
    slice_path, slice_meta = cfolder / "source.mp4", cfolder / "slice.json"
    key = {"parts": [[round(a, 3), round(b, 3)] for a, b in parts]}
    if not (slice_path.exists() and read_json(slice_meta) == key):
        if not source.exists():
            raise PermanentError("El video fuente se borró con «Limpiar» y los bordes cambiaron: "
                                 "no hay de dónde recortar.")
        cut_slice(source, parts, slice_path)
        write_json(slice_meta, key)
    duration = sum(b - a for a, b in parts)

    # 2 · Reencuadre (caché por trozo + diseño)
    mode = clip.get("layoutMode") or "auto"
    reframed, rmeta = cfolder / "reframed.mp4", cfolder / "reframe.json"
    rkey = {**key, "mode": mode}
    if not (reframed.exists() and read_json(rmeta) == rkey):
        reframe_adapter.reframe(slice_path, reframed, mode, width=OUT_W, height=OUT_H)
        write_json(rmeta, rkey)
    layout = layout_ranges.read(reframed)

    # 3 · Subtítulos + gancho (ASS)
    captions = read_json(cfolder / "captions.json", {}) or {}
    words = clip_words(captions, parts)
    template = clip.get("templateId") or ass_builder.DEFAULT_TEMPLATE
    keep = None
    if clip.get("smartCut"):
        silences = detect_silences(str(reframed), ffmpeg=ffmpeg_bin(), noise_db=-35, min_dur=0.6)
        segs = smartcut.keep_segments(duration, silences, words)
        if smartcut.kept_duration(segs) >= 0.6 * duration and len(segs) > 1:
            keep = segs
    if keep:
        ass_builder.write_ass(cfolder / "clip.ass", words, template_id=template, hook_text="",
                              clip_duration=duration, layout=layout)
        ass_builder.write_ass(cfolder / "hook.ass", [], template_id=template, hook_text=clip.get("hook") or "",
                              clip_duration=smartcut.kept_duration(keep))
    else:
        ass_builder.write_ass(cfolder / "clip.ass", words, template_id=template, hook_text=clip.get("hook") or "",
                              clip_duration=duration, layout=layout)
    if not has_libass():
        raise PermanentError("El ffmpeg encontrado no tiene libass (filtro «ass»). En Mac: "
                             "brew install ffmpeg-full, o define FFMPEG_BIN en .env.")

    # 4 · Pasada final: zoom → subtítulos → corte inteligente → gancho → audio
    only_general = layout and all(r["layout"] == "general" for r in layout)
    zoom = None if only_general else s.ken_burns_zoom
    tmp_out, final = cfolder / "final.tmp.mp4", cfolder / "final.mp4"
    expected = smartcut.kept_duration(keep) if keep else duration
    cmd = _final_command(cfolder, reframed, tmp_out, ass_main="clip.ass", ass_hook="hook.ass" if keep else None,
                         keep=keep, zoom=zoom, duration=duration)
    qa = None
    for attempt in range(2):
        # cwd = carpeta del clip: rutas relativas en el filtergraph (sin escapar espacios).
        run(cmd, what="render final", timeout=3600, cwd=cfolder)
        # 5 · Revisión de calidad
        qa = media_qa.inspect_clip(str(tmp_out), expected_duration=expected, expected_aspect=OUT_W / OUT_H,
                                   ffmpeg=ffmpeg_bin(), ffprobe=ffprobe_bin(), target_lufs=s.target_lufs,
                                   smartcut_applied=bool(keep))
        if not qa["critical"]:
            break
        log.warning("render de %s con defectos (%s); intento %d", clip["id"], qa["issues"], attempt + 1)
    if qa and qa["critical"]:
        raise RuntimeError("revisión de calidad: " + "; ".join(qa["issues"]))
    tmp_out.replace(final)

    thumb = cfolder / "thumb.jpg"
    reframe_adapter.pick_cover(final, thumb)
    return {
        "outputPath": _rel(final),
        "thumbPath": _rel(thumb) if thumb.exists() else None,
        "cropPath": _rel(cfolder / "crop.json") if (cfolder / "crop.json").exists() else None,
        "captionsPath": _rel(cfolder / "captions.json") if (cfolder / "captions.json").exists() else None,
        "qaWarnings": json.dumps(qa["warnings"] if qa else [], ensure_ascii=False),
        "layout": layout,
    }


def run_task(clip_id: str, payload: dict) -> None:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise PermanentError("El clip ya no existe.")
    db.update_clip(clip_id, renderStatus="RUNNING", renderError=None)
    result = render_clip(clip)
    result.pop("layout", None)
    db.update_clip(clip_id, renderStatus="DONE", renderError=None, **result)
