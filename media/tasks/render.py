"""Tarea `render`: clip final listo para subir.

Orden de capas: recorte 16:9 (uno o varios tramos) → reencuadre (automático
o manual con zoom y posición) → zoom lento →
efectos de color → subtítulos → emojis → corte inteligente (opcional) →
gancho → audio (normalizado y luego volumen/silencio del estudio).

El trozo 16:9 (`source.mp4` del clip) y el reencuadre (`reframed.mp4`) quedan
en caché: cambiar plantilla, palabras, gancho, efectos o audio solo repite la
última pasada; cambiar de diseño re-renderiza desde el trozo guardado. Todas
las pasadas usan el mismo CRF (services/ffmpeg.py).

El avance (0–100) se guarda en Clip.renderProgress y el render se puede
cancelar desde la API (services/cancel.py): el MP4 anterior queda intacto.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from media.config import settings
from media.errors import PermanentError
from media.services import (ass_builder, cancel, cover, db, edit_doc, emoji_art, fonts, layout_ranges,
                            media_qa, punch, reframe_adapter, smartcut, source_cache)
from media.services.atomic import read_json, write_json
from media.services.cut_ops import detect_silences
from media.services.transcript import join_number_fragments
from media.services.ffmpeg import (LOUDNORM_TRUE_PEAK, METADATA_SCRUB, ffmpeg_bin, ffprobe_bin, has_libass, run,
                                   run_progress, video_args, video_size)
from media.tasks.common import clip_folder, log, project_folder

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30
KENBURNS_SUPERSAMPLE = 1.5
KENBURNS_ANCHOR_Y = 0.35


def _rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(settings().data_dir.resolve()))


def slice_plan(clip: dict) -> list[tuple[float, float]]:
    """Tramos del video fuente que forman el clip, en orden."""
    return edit_doc.clip_parts(clip)


def clip_words(captions: dict, parts: list[tuple[float, float]]) -> list[dict]:
    """Palabras absolutas de captions.json → línea de tiempo del clip (con las
    cifras partidas por Whisper vueltas a unir: «40» + «.000» → «40.000»)."""
    out, offset = [], 0.0
    for a, b in parts:
        for w in captions.get("words") or []:
            mid = (w["start"] + w["end"]) / 2
            if a <= mid < b and str(w.get("w", "")).strip():
                word = {"w": w["w"], "start": round(max(0.0, w["start"] - a) + offset, 3),
                        "end": round(min(b, w["end"]) - a + offset, 3)}
                if w.get("hl"):
                    word["hl"] = True
                out.append(word)
        offset += b - a
    return join_number_fragments(out)


def cut_slice(source: Path, parts: list[tuple[float, float]], dest: Path) -> None:
    """Trozo 16:9 del clip (CFR, H.264, AAC). Con varios tramos se concatenan."""
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
    args += [*video_args(faststart=False), *METADATA_SCRUB, "-fps_mode", "cfr", "-c:a", "aac", "-b:a", "192k",
             str(tmp)]
    run(args, what="recortar el trozo 16:9", timeout=3600)
    tmp.replace(dest)


def kenburns_filter(zoom: float | None, duration: float, width: int, height: int,
                    punches: list[float] | tuple = ()) -> str | None:
    """Zoom lento 1,00 → ``zoom`` sin saltos, más los acercamientos en las
    palabras fuertes (services/punch.py), multiplicados en la misma expresión.

    `zoompan` recorta con desplazamientos enteros: sobre el cuadro final cada
    paso sería un salto de un píxel visible. Se trabaja sobre el cuadro
    escalado 1,5× (1620×2880 en vertical), así cada paso entero equivale a
    2/3 de píxel del resultado. El zoom se ancla al tercio superior (donde
    suele estar la cara), no al centro.
    """
    slow = bool(zoom and zoom > 1.0)
    punch_z = punch.zoom_expression(list(punches), OUT_FPS)
    if duration <= 0 or not (slow or punch_z):
        return None
    frames = max(1, int(duration * OUT_FPS))
    z = f"min(1+{(zoom - 1) / frames:.8f}*on,{zoom:.4f})" if slow else "1"
    if punch_z:
        z = f"{z}*{punch_z}"
    sw = int(round(width * KENBURNS_SUPERSAMPLE / 2)) * 2
    sh = int(round(height * KENBURNS_SUPERSAMPLE / 2)) * 2
    return (f"scale={sw}:{sh}:flags=lanczos,fps={OUT_FPS},"
            f"zoompan=z='{z}'"
            f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)*{KENBURNS_ANCHOR_Y}'"
            f":d=1:s={width}x{height}:fps={OUT_FPS},setsar=1")


def emoji_chain(index: int, item: dict, cur: str, label: str) -> list[str]:
    """Emoji (PNG en bucle, entrada ``index``) sobre ``cur``: aparece con un
    fundido y un pequeño salto hacia arriba y se va con fundido."""
    a, b = float(item["start"]), float(item["end"])
    fin, fout = min(0.12, (b - a) / 3), min(0.1, (b - a) / 3)
    rise = max(4, int(round(item["size"] * 0.15)))
    return [
        f"[{index}:v]format=rgba,fade=t=in:st={a:.3f}:d={fin:.3f}:alpha=1,"
        f"fade=t=out:st={b - fout:.3f}:d={fout:.3f}:alpha=1[em{index}]",
        f"{cur}[em{index}]overlay=x={item['x']}:y='{item['y']}+{rise}*max(0,1-(t-{a:.3f})/0.18)'"
        f":enable='between(t,{a:.3f},{b:.3f})':eof_action=pass:format=auto{label}",
    ]


def final_command(reframed: Path | str, out: Path | str, *, fonts_rel: str, ass_main: str,
                  ass_hook: str | None, keep: list[tuple[float, float]] | None, zoom: float | None,
                  duration: float, width: int = OUT_W, height: int = OUT_H, effects: str | None = None,
                  emojis: list[dict] | tuple = (),
                  audio: dict | None = None, preset: str = "tiktok",
                  punches: list[float] | tuple = (), hook_emoji: dict | None = None) -> list[str]:
    """Pasada final (un solo encode). Rutas de los ASS relativas al cwd."""
    inputs = ["-i", str(reframed)]
    chains: list[str] = []
    kb = kenburns_filter(zoom, duration, width, height, punches)
    chains.append(f"[0:v]{kb or 'null'}[k]")
    cur, idx = "[k]", 1
    mid = [effects] if effects else []
    mid.append(f"ass={ass_main}:fontsdir={fonts_rel}")
    chains.append(f"{cur}{','.join(mid)}[c]")
    cur = "[c]"
    for j, item in enumerate(emojis):
        inputs += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{duration:.3f}", "-i", str(item["path"])]
        chains += emoji_chain(idx, item, cur, f"[e{j}]")
        cur, idx = f"[e{j}]", idx + 1
    tail = []
    if keep:
        tail.append(smartcut.video_filter(keep))
    if ass_hook:
        tail.append(f"ass={ass_hook}:fontsdir={fonts_rel}")
    if hook_emoji:
        # El emoji del gancho va después del corte inteligente, en el tiempo del video final
        # (el gancho también: su .ass se aplica ahí).
        inputs += ["-loop", "1", "-framerate", str(OUT_FPS), "-t", f"{duration:.3f}", "-i", str(hook_emoji["path"])]
        if tail:
            chains.append(f"{cur}{','.join(tail)}[hh]")
            cur, tail = "[hh]", []
        chains += emoji_chain(idx, hook_emoji, cur, "[hv]")
        cur = "[hv]"
    tail += [f"fps={OUT_FPS}", "format=yuv420p"]
    chains.append(f"{cur}{','.join(tail)}[v]")
    a = [smartcut.audio_filter(keep)] if keep else []
    a.append(f"loudnorm=I={settings().target_lufs:g}:TP={LOUDNORM_TRUE_PEAK:g}:LRA=11")
    gain = edit_doc.audio_filter(audio or {})
    if gain:
        a.append(gain)  # después de normalizar: si no, loudnorm lo desharía
    a.append("aresample=48000")
    chains.append(f"[0:a]{','.join(a)}[a]")
    return [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]", *METADATA_SCRUB,
            *video_args(faststart=True), *edit_doc.maxrate_args(preset), "-r", str(OUT_FPS),
            "-c:a", "aac", "-b:a", "192k", str(out)]


def static_reframe(slice_path: Path, reframed: Path, framing: dict, width: int, height: int,
                   duration: float, on_progress=None, cancelled=None) -> None:
    """Encuadre manual: escala × zoom, recorte con ancla y fondo desenfocado."""
    sw, sh = video_size(slice_path)
    if not sw or not sh:
        raise RuntimeError("no se pudo leer el tamaño del trozo 16:9")
    tmp = reframed.with_name("reframed.tmp.mp4")
    graph = edit_doc.framing_filter(sw, sh, width, height, framing)
    try:
        run_progress([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(slice_path),
                      "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0", *METADATA_SCRUB,
                      *video_args(faststart=False), "-fps_mode", "cfr", "-c:a", "copy", str(tmp)],
                     total=duration, on_progress=on_progress, cancelled=cancelled, what="encuadre manual")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(reframed)
    layout_ranges.write(reframed, [{"start": 0.0, "end": duration, "layout": "manual"}])
    (reframed.parent / "crop.json").unlink(missing_ok=True)


BASE_TOLERANCE = 0.05


def map_to_base(base_parts: list[tuple[float, float]], parts: list[tuple[float, float]],
                tol: float = BASE_TOLERANCE) -> list[tuple[float, float]] | None:
    """Recorte rápido: dónde está cada tramo nuevo dentro del video base.

    El base es el último reencuadre completo (sus tramos, concatenados). Si
    cada tramo nuevo cae entero dentro de uno de los del base, se devuelven
    sus ``(inicio, fin)`` en la línea de tiempo del base; si alguno se sale,
    None (hay que reencuadrar desde la fuente)."""
    offsets, acc = [], 0.0
    for a, b in base_parts:
        offsets.append(acc)
        acc += b - a
    out = []
    for a, b in parts:
        hit = None
        for (ba, bb), off in zip(base_parts, offsets):
            if a >= ba - tol and b <= bb + tol:
                s = off + max(0.0, a - ba)
                e = off + min(bb, b) - ba
                if e - s >= 0.1:
                    hit = (round(s, 3), round(e, 3))
                break
        if hit is None:
            return None
        out.append(hit)
    return out


def recut_from_base(base: Path, dest: Path, mapping: list[tuple[float, float]], *,
                    on_progress=None, cancelled=None) -> None:
    """Corta y une tramos del video base ya reencuadrado (sin volver a
    rastrear caras): segundos en vez de minutos. Cortes exactos al cuadro."""
    parts = []
    for i, (a, b) in enumerate(mapping):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    joins = "".join(f"[v{i}][a{i}]" for i in range(len(mapping)))
    parts.append(f"{joins}concat=n={len(mapping)}:v=1:a=1[v][a]")
    tmp = dest.with_name("reframed.cut.tmp.mp4")
    try:
        run_progress([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base),
                      "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", *METADATA_SCRUB,
                      *video_args(faststart=False), "-fps_mode", "cfr", "-r", str(OUT_FPS),
                      "-c:a", "aac", "-b:a", "192k", str(tmp)],
                     total=sum(b - a for a, b in mapping), on_progress=on_progress, cancelled=cancelled,
                     what="recorte rápido")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)


def _link(src: Path, dst: Path) -> None:
    """dst = src sin copiar (hardlink; copia si no se puede) y su sidecar de diseño."""
    source_cache.link_or_copy(src, dst)
    layout_ranges.write(dst, layout_ranges.read(src))


class _Progress:
    """Guarda el avance en la BD sin escribir en cada cuadro."""

    def __init__(self, clip_id: str):
        self.clip_id, self.last, self.t = clip_id, -1, 0.0

    def __call__(self, value: float) -> None:
        v = int(max(0, min(99, round(value))))
        now = time.monotonic()
        if v != self.last and (v - self.last >= 3 or now - self.t >= 1.0):
            self.last, self.t = v, now
            db.update_clip(self.clip_id, renderProgress=v)


def render_clip(clip: dict, *, on_progress=None, cancelled=None) -> dict:
    s = settings()
    report = on_progress or (lambda _v: None)
    project = db.get_project(clip["projectId"])
    if project is None:
        raise PermanentError("El proyecto ya no existe.")
    folder = project_folder(project["id"])
    cfolder = clip_folder(project["id"], clip["id"])
    source = folder / "source.mp4"
    doc = edit_doc.parse(clip.get("edit"))
    framing = doc["framing"]

    # 1 · Tramos y tamaño de salida
    report(1)
    parts = edit_doc.clip_parts(clip, doc)
    slice_path, slice_meta = cfolder / "source.mp4", cfolder / "slice.json"
    key = {"parts": [[round(a, 3), round(b, 3)] for a, b in parts]}
    duration = sum(b - a for a, b in parts)
    probe = slice_path if slice_path.exists() else source
    src_w, src_h = video_size(probe) if probe.exists() else (0, 0)
    width, height = edit_doc.output_size(framing["aspect"], src_w, src_h)
    manual = framing["mode"] == "manual" or framing["aspect"] == "original"
    mode = clip.get("layoutMode") or "auto"
    if manual:
        rkey = {**key, "framing": framing, "size": [width, height]}
    else:
        rkey = {**key, "mode": mode} if (width, height) == (OUT_W, OUT_H) else \
            {**key, "mode": mode, "size": [width, height]}
        rkey["engine"] = reframe_adapter.ENGINE_VERSION  # encuadre mejorado: no reutilizar el anterior

    # 2 · Reencuadre. Caché exacta (reframe.json) y, si solo cambiaron los
    # tramos y todos caben en el último reencuadre completo (el «base»), se
    # recortan de él en segundos en vez de volver a rastrear caras.
    reframed, rmeta = cfolder / "reframed.mp4", cfolder / "reframe.json"
    base, bmeta = cfolder / "reframed.base.mp4", cfolder / "reframe.base.json"
    if not base.exists() and reframed.exists() and read_json(rmeta):
        _link(reframed, base)  # clips reencuadrados antes de existir el base
        write_json(bmeta, read_json(rmeta))
    if not (reframed.exists() and read_json(rmeta) == rkey):
        step = on_progress and _span(report, 6, 55)
        bkey = read_json(bmeta) if base.exists() else None
        same = bool(bkey) and {k: v for k, v in bkey.items() if k != "parts"} == \
            {k: v for k, v in rkey.items() if k != "parts"}
        mapping = map_to_base([tuple(p) for p in bkey["parts"]], parts) if same else None
        if mapping is not None and bkey == rkey:
            _link(base, reframed)
        elif mapping is not None:
            log.info("recorte rápido de %s desde el reencuadre base", clip["id"])
            recut_from_base(base, reframed, mapping, on_progress=step, cancelled=cancelled)
            layout_ranges.write(reframed, layout_ranges.remap(layout_ranges.read(base), mapping))
        else:
            report(3)
            if not (slice_path.exists() and read_json(slice_meta) == key):
                if not source.exists():
                    raise PermanentError("El video fuente se borró con «Limpiar» y los tramos cambiaron: "
                                         "no hay de dónde recortar.")
                cut_slice(source, parts, slice_path)
                write_json(slice_meta, key)
            report(6)
            if manual:
                static_reframe(slice_path, reframed, framing, width, height, duration, step, cancelled)
            else:
                # Puede ser un enlace al base: se suelta antes de que ffmpeg lo reescriba.
                reframed.unlink(missing_ok=True)
                reframe_adapter.reframe(slice_path, reframed, mode, width=width, height=height,
                                        on_progress=step, cancelled=cancelled)
            _link(reframed, base)
            write_json(bmeta, rkey)
        write_json(rmeta, rkey)
    layout = layout_ranges.read(reframed)
    report(56)

    # 3 · Subtítulos + gancho (ASS) y emojis
    captions = read_json(cfolder / "captions.json", {}) or {}
    words = clip_words(captions, parts)
    template = clip.get("templateId") or ass_builder.DEFAULT_TEMPLATE
    font = doc["font"]
    ass_opts = {"template_id": template, "layout": layout, "width": width, "height": height, "font": font}
    hook_seconds = doc["hookSeconds"] or ass_builder.hook_display_seconds(
        clip.get("hook") or "", ass_builder.load_template(template), spoken=_spoken_hook(clip, parts))
    keep = None
    if clip.get("smartCut"):
        silences = detect_silences(str(reframed), ffmpeg=ffmpeg_bin(), noise_db=-35, min_dur=0.6)
        segs = smartcut.keep_segments(duration, silences, words)
        if smartcut.kept_duration(segs) >= 0.6 * duration and len(segs) > 1:
            keep = segs
    if keep:
        ass_builder.write_ass(cfolder / "clip.ass", words, hook_text="", clip_duration=duration, **ass_opts)
        ass_builder.write_ass(cfolder / "hook.ass", [], hook_text=clip.get("hook") or "",
                              clip_duration=smartcut.kept_duration(keep), hook_seconds=hook_seconds, **ass_opts)
    else:
        ass_builder.write_ass(cfolder / "clip.ass", words, hook_text=clip.get("hook") or "",
                              clip_duration=duration, hook_seconds=hook_seconds, **ass_opts)
    if not has_libass():
        raise PermanentError("El ffmpeg encontrado no tiene libass (filtro «ass»). En Mac: "
                             "brew install ffmpeg-full, o define FFMPEG_BIN en .env.")

    emojis = []
    if ass_builder.load_template(template).get("emoji") and emoji_art.available():
        for item in ass_builder.plan_emojis(words, clip_duration=duration, **ass_opts):
            png = emoji_art.emoji_png(item["emoji"], item["size"])
            if png is not None:
                emojis.append({**item, "path": str(png)})

    hook_emoji = None  # el emoji del gancho (a color, encima de su caja); sin fuente de emojis, el video sigue sin él
    if emoji_art.available():
        item = ass_builder.plan_hook_emoji(clip.get("hook") or "", tpl=ass_builder.load_template(template),
                                           width=width, height=height, seconds=hook_seconds,
                                           clip_duration=smartcut.kept_duration(keep) if keep else duration)
        png = emoji_art.emoji_png(item["emoji"], item["size"]) if item else None
        if item and png is not None:
            hook_emoji = {**item, "path": str(png)}

    report(60)

    # 4 · Pasada final
    only_general = layout and all(r["layout"] == "general" for r in layout)
    zoom = None if (manual or only_general) else s.ken_burns_zoom
    # Acercamientos en palabras fuertes: solo con encuadre automático (en el
    # manual el encuadre lo decidiste tú) y nunca sobre tramos apilados o con
    # fondo desenfocado.
    punches = punch.beat_times(words, duration, layout=layout) if (doc["punch"] and not manual) else []
    tmp_out, final = cfolder / "final.tmp.mp4", cfolder / "final.mp4"
    expected = smartcut.kept_duration(keep) if keep else duration
    fonts_rel = os.path.relpath(fonts.fonts_dir(), cfolder)
    cmd = final_command(reframed.name, tmp_out.name, fonts_rel=fonts_rel, ass_main="clip.ass",
                        ass_hook="hook.ass" if keep else None, keep=keep, zoom=zoom, duration=duration,
                        width=width, height=height, effects=edit_doc.effects_filter(doc["effects"], width),
                        emojis=emojis, audio=doc["audio"], preset=doc["preset"],
                        punches=punches, hook_emoji=hook_emoji)
    muted = bool(doc["audio"]["muted"])
    qa = None
    for attempt in range(2):
        # cwd = carpeta del clip: rutas relativas en el filtergraph (sin escapar espacios).
        try:
            run_progress(cmd, total=expected, on_progress=_span(report, 60, 97), cancelled=cancelled,
                         what="render final", timeout=3600, cwd=cfolder)
        except BaseException:
            tmp_out.unlink(missing_ok=True)  # el MP4 anterior (si hay) queda intacto
            raise
        # 5 · Revisión de calidad
        qa = media_qa.inspect_clip(str(tmp_out), expected_duration=expected, expected_aspect=width / height,
                                   ffmpeg=ffmpeg_bin(), ffprobe=ffprobe_bin(),
                                   target_lufs=None if muted else s.target_lufs, smartcut_applied=bool(keep))
        if muted:  # silenciado a propósito: no es un defecto
            qa["warnings"] = [w for w in qa["warnings"] if not w.startswith(("audio muy bajo", "loudness"))]
        if not qa["critical"]:
            break
        log.warning("render de %s con defectos (%s); intento %d", clip["id"], qa["issues"], attempt + 1)
    if qa and qa["critical"]:
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError("revisión de calidad: " + "; ".join(qa["issues"]))
    tmp_out.replace(final)
    report(98)

    thumb = cfolder / "thumb.jpg"
    reframe_adapter.pick_cover(final, thumb)
    cover_path = _make_cover(clip, cfolder)
    return {
        "outputPath": _rel(final),
        "thumbPath": _rel(thumb) if thumb.exists() else None,
        "coverPath": cover_path,
        "cropPath": _rel(cfolder / "crop.json") if (cfolder / "crop.json").exists() else None,
        "captionsPath": _rel(cfolder / "captions.json") if (cfolder / "captions.json").exists() else None,
        "qaWarnings": json.dumps(qa["warnings"] if qa else [], ensure_ascii=False),
        "layout": layout,
    }


def _make_cover(clip: dict, cfolder: Path) -> str | None:
    """Portada con el gancho en grande (services/cover.py). Un fallo aquí no
    tumba el render: el clip queda listo y la portada se rehace desde el estudio."""
    try:
        fresh = db.get_clip(clip["id"]) or clip  # ajustes guardados mientras renderizaba
        return _rel(cover.make_cover({**clip, "cover": fresh.get("cover")}, cfolder)["path"])
    except Exception as exc:
        log.warning("portada de %s: %s", clip["id"], exc)
        existing = cfolder / cover.FILE
        return _rel(existing) if existing.exists() else None


def _spoken_hook(clip: dict, parts: list[tuple[float, float]]) -> float | None:
    """Segundos del clip hasta que termina el gancho hablado (según el arco
    del análisis), contando el avance si abre el clip. None si no se sabe."""
    try:
        arc = (json.loads(clip.get("signals") or "{}") or {}).get("arc") or {}
    except (TypeError, ValueError):
        return None
    spoken = arc.get("hook_seconds")
    if not spoken:
        return None
    main = next((p for p in parts if abs(p[0] - float(clip["startSec"])) < 0.5), None)
    if main is None:
        return None  # los tramos cambiaron en el estudio: ya no se sabe dónde cae
    return float(spoken) + sum(b - a for a, b in parts[:parts.index(main)])


def _span(report, a: float, b: float):
    return lambda frac: report(a + (b - a) * frac)


def run_task(clip_id: str, payload: dict) -> None:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise PermanentError("El clip ya no existe.")
    key = cancel.render_key(clip_id)
    cancel.clear(key)
    revision = int(clip.get("editRevision") or 0)
    db.update_clip(clip_id, renderStatus="RUNNING", renderError=None, renderProgress=0)
    progress = _Progress(clip_id)
    try:
        result = render_clip(clip, on_progress=progress, cancelled=lambda: cancel.requested(key))
    finally:
        cancel.clear(key)
    result.pop("layout", None)
    db.update_clip(clip_id, renderStatus="DONE", renderError=None, renderProgress=100,
                   renderedRevision=revision, **result)
