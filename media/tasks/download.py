"""Tarea `download`: video H.264 + info.json + heatmap + subtítulos.

La escalera de formatos y la clasificación de errores están adaptadas de
ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/download.py (_FORMAT_LADDER,
classify_download_error).
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: primero el formato del plan (`bv*[vcodec^=avc1][height<=1080]+ba/b`);
subtítulos json3 en un segundo paso con el mismo info.json (un fallo de
subtítulos nunca tumba la descarga); si llega AV1/VP9 se transcodifica a H.264.

Salida en data/projects/<id>/: source.mp4, source.info.json, audio.wav y
source.<lang>.json3 cuando YouTube tiene subtítulos.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from media.config import settings
from media.errors import PermanentError
from media.services import db, source_cache, sources, transcript
from media.services.atomic import read_json, write_json
from media.services.ffmpeg import extract_audio, ffmpeg_bin, probe_json, run, video_args
from media.tasks import preflight
from media.tasks.common import check_stop, log, progress, project_folder, require_project

FORMAT_LADDER = (
    "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/"  # con audio AAC si existe
    "bv*[vcodec^=avc1][height<=1080]+ba/"
    "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[vcodec^=avc1]+bestaudio/"
    "best[ext=mp4]/bestvideo*+bestaudio/best"
)

# Cadena de clientes de YouTube: si YouTube
# responde 403 o sin formatos con el cliente por defecto, se prueba otro. El
# cliente por defecto se repite una vez: el 403 del primer pedido suele ser
# transitorio (medido: el segundo intento descarga bien). `tv_embedded` ya no
# existe en yt-dlp (2026.08): se quitó. Último recurso: `default,mweb`, que con cookies descarga donde los
# clientes por defecto responden «Video unavailable»; sin token PO, mweb solo
# ofrece 360p, por eso va al final.
PLAYER_CLIENT_CHAIN = (None, None, ["tv", "web_safari"], ["default", "mweb"])

# Kick: el VOD es un HLS con video y audio juntos (H.264 hasta 1080p60), sin
# clientes ni subtítulos que probar: dos intentos con el formato por defecto.
KICK_FORMAT_LADDER = "bv*[vcodec^=avc1][height<=1080]+ba/b[vcodec^=avc1][height<=1080]/best[height<=1080]/best"
KICK_CHAIN = (None, None)
SITE_NAME = {"youtube": "YouTube", "kick": "Kick"}

_YT_RE = re.compile(r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)

_FATAL = (
    "private video", "this video is private", "video has been removed", "removed by the user",
    "account associated with this video has been terminated", "video is no longer available",
    "video unavailable", "not available in your country", "confirm your age", "members-only",
    "join this channel", "is not a valid url", "unsupported url", "premieres in",
)


def classify_download_error(msg: str) -> str:
    """'fatal' (no reintentar) | 'bot' (pide cookies) | 'retry'."""
    m = (msg or "").lower()
    if "sign in to confirm you" in m and "bot" in m:
        return "bot"
    return "fatal" if any(s in m for s in _FATAL) else "retry"


def is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.match((url or "").strip()))


def _base_opts(folder: Path) -> dict:
    s = settings()
    opts = {
        "outtmpl": str(folder / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "ffmpeg_location": str(Path(ffmpeg_bin()).parent) if "/" in ffmpeg_bin() else None,
    }
    if s.ytdlp_cookies_from_browser:
        opts["cookiesfrombrowser"] = (s.ytdlp_cookies_from_browser,)
    return {k: v for k, v in opts.items() if v is not None}


def _download_remote(project: dict, folder: Path) -> dict:
    """Descarga un video de YouTube o de Kick (VOD), entero o solo un tramo."""
    import yt_dlp

    pid = project["id"]
    url = project["sourceUrl"] or ""
    src = sources.parse(url)
    if src is None:
        if is_youtube_url(url):  # de YouTube, pero no de un video: lista, canal o búsqueda
            raise PermanentError("El enlace no es un video de YouTube (parece una lista, un canal o una "
                                 "búsqueda). Abre el video y pega el enlace de ese video.")
        raise PermanentError("La URL no es de YouTube ni de Kick.")
    if src["type"] == "youtube" and not is_youtube_url(url):
        raise PermanentError("La URL no parece de YouTube.")
    if src["kind"] != "video":
        # yt-dlp recorre listas, canales y búsquedas entrada por entrada (aun
        # con noplaylist): se rechazan antes de hacer una sola petición.
        raise PermanentError(
            "El enlace de Kick es de un clip o de un canal: pega el de un VOD (kick.com/canal/videos/…)."
            if src["type"] == "kick" else
            "El enlace no es un video de YouTube (parece una lista, un canal o una "
            "búsqueda). Abre el video y pega el enlace de ese video.")
    site = SITE_NAME[src["type"]]
    if src["type"] == "kick":
        try:
            url = sources.canonical_url(src)  # yt-dlp solo entiende kick.com/<canal>/videos/<id>
        except sources.SourceError as exc:
            raise PermanentError(str(exc)) from exc
    window = None
    if project.get("rangeEndSec") is not None:
        try:
            window = sources.check_range(project.get("rangeStartSec"), project["rangeEndSec"], settings().max_video_minutes)
        except sources.SourceError as exc:
            raise PermanentError(str(exc)) from exc
    state = {"stream": 0, "last": -1}

    def hook(d):
        if d.get("status") == "finished":
            state["stream"] += 1
            return
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        frac = (d.get("downloaded_bytes") or 0) / total if total else 0
        value = 1 + (14 * frac if state["stream"] == 0 else 15 + 3 * frac)
        if int(value) != state["last"]:
            state["last"] = int(value)
            progress(pid, value, stage="Descargando el video")

    def match(info, *, incomplete):
        if incomplete:
            return None
        try:
            # Con tramo, lo que se descarga (y ocupa disco) es el tramo, no el directo entero.
            length = (window[1] - window[0]) if window else info.get("duration")
            preflight.check(length, folder, is_live=bool(info.get("is_live")))
        except PermanentError as exc:
            state["rejected"] = str(exc)
            return str(exc)
        return None

    base = {**_base_opts(folder), "format": KICK_FORMAT_LADDER if src["type"] == "kick" else FORMAT_LADDER,
            "merge_output_format": "mp4", "writeinfojson": True, "progress_hooks": [hook], "match_filter": match}
    if window:
        from yt_dlp.utils import download_range_func
        # Solo el tramo (ffmpeg lo corta al bajar); force_keyframes: el corte empieza en el segundo pedido.
        base["download_ranges"] = download_range_func(None, [window])
        base["force_keyframes_at_cuts"] = True
    chain = PLAYER_CLIENT_CHAIN if src["type"] == "youtube" else KICK_CHAIN
    info = None
    for attempt, clients in enumerate(chain):
        opts = dict(base)
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc)
            kind = classify_download_error(msg)
            if kind == "fatal":
                raise PermanentError(f"{site} no permite descargar este video: {msg[:300]}") from exc
            if kind == "bot":
                raise PermanentError("YouTube pide verificar que no eres un bot. Configura "
                                     "YTDLP_COOKIES_FROM_BROWSER=chrome (o tu navegador) en .env y reintenta.") from exc
            if attempt == len(chain) - 1:
                raise
            log.warning("descarga falló con el cliente %s (%s); pruebo de nuevo", clients or "por defecto", msg[:160])
            time.sleep(3)
            for part in folder.glob("source.*.part"):
                part.unlink(missing_ok=True)
    if state.get("rejected"):
        raise PermanentError(state["rejected"])
    if not info:
        raise RuntimeError("yt-dlp no devolvió información del video")

    info_path = folder / "source.info.json"
    if window:  # la ficha cuenta el video entero: se ajusta al tramo que hay en disco
        # (se parte del .info.json que escribió yt-dlp: el objeto en memoria puede no ser serializable)
        info = sources.apply_range(read_json(info_path, {}) or {k: info.get(k) for k in (
            "id", "title", "uploader", "channel", "duration", "timestamp", "upload_date", "view_count", "thumbnail")}, *window)
        write_json(info_path, info)
    if src["type"] != "youtube":
        return info  # Kick no trae subtítulos: la transcripción es con Whisper
    # Subtítulos: segundo paso sobre el mismo info.json (sin volver a extraer).
    langs = transcript.subtitle_langs(info)
    try:
        sub_opts = {**_base_opts(folder), "skip_download": True, "writesubtitles": True,
                    "writeautomaticsub": True, "subtitleslangs": langs, "subtitlesformat": "json3/vtt/best"}
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            ydl.download_with_info_file(str(info_path))
    except Exception as exc:  # 429 de subtítulos, PO token… → respaldo en transcribe
        log.warning("subtítulos no descargados (%s); se usará el respaldo", str(exc)[:200])
    return info


def _ensure_h264_mp4(src: Path, dst: Path) -> None:
    """AV1/VP9 (o contenedor raro) → H.264 una sola vez; si ya es H.264 en mp4,
    se deja tal cual (sin recodificar)."""
    data = probe_json(src)
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise PermanentError("El archivo no tiene pista de video.")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_audio:
        raise PermanentError("El archivo no tiene audio: ClipAI necesita voz para elegir momentos.")
    fmt = (data.get("format") or {}).get("format_name", "")
    if v.get("codec_name") == "h264" and "mp4" in fmt and v.get("pix_fmt") in ("yuv420p", "yuvj420p"):
        if src != dst:
            shutil.move(str(src), str(dst))
        return
    log.info("transcodificando %s (%s) a H.264", src.name, v.get("codec_name"))
    tmp = dst.with_name("source.h264.tmp.mp4")
    run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-map", "0:v:0", "-map", "0:a:0", "-vf", "scale='min(1920,iw)':-2", *video_args(faststart=True),
         "-c:a", "aac", "-b:a", "192k", str(tmp)], what="transcodificar a H.264", timeout=6 * 3600)
    tmp.replace(dst)
    if src != dst and src.exists():
        src.unlink()


def run_task(project_id: str, payload: dict) -> None:
    project = require_project(project_id)
    folder = project_folder(project_id)
    source, audio, info_path = folder / "source.mp4", folder / "audio.wav", folder / "source.info.json"

    if source.exists() and audio.exists() and info_path.exists():
        log.info("descarga ya hecha (punto de control)")
    else:
        progress(project_id, 1, status="DOWNLOADING", stage="Preparando la descarga")
        remote = project["sourceType"] in ("youtube", "kick")
        sibling = source_cache.find_sibling_source(project) if project["sourceType"] == "youtube" else None
        if sibling is not None:
            # El mismo video ya está en otro proyecto: se enlaza, sin volver a bajarlo.
            log.info("video reutilizado de %s", sibling.name)
            progress(project_id, 15, stage="Reutilizando el video ya descargado")
            source_cache.reuse_source(sibling, folder)
        elif remote:
            info = _download_remote(project, folder)
            downloaded = next((p for p in folder.glob("source.*")
                               if p.suffix in (".mp4", ".mkv", ".webm") and ".tmp" not in p.name), None)
            if downloaded is None:
                raise RuntimeError("yt-dlp terminó sin archivo de video")
            check_stop(project_id)
            progress(project_id, 18, stage="Verificando códec")
            _ensure_h264_mp4(downloaded, source)
        else:
            upload = next((p for p in folder.glob("upload.*")), None)
            if upload is None:
                raise PermanentError("No se encontró el archivo subido.")
            dur = float((probe_json(upload).get("format") or {}).get("duration") or 0)
            preflight.check(dur, folder)
            source_cache.remember_key(folder, "up-" + source_cache.file_fingerprint(upload))
            progress(project_id, 8, stage="Preparando el archivo")
            _ensure_h264_mp4(upload, source)
            info = {"title": project.get("title") or upload.stem, "duration": dur, "language": None}
            write_json(info_path, info)
        if sibling is None:  # el reutilizado ya trae su audio.wav
            progress(project_id, 19, stage="Extrayendo audio")
            tmp_audio = folder / "audio.tmp.wav"
            extract_audio(source, tmp_audio)
            tmp_audio.replace(audio)

    info = read_json(info_path, {}) or {}
    if project["sourceType"] in ("youtube", "kick") and not (folder / source_cache.KEY_FILE).exists():
        src = sources.parse(project.get("sourceUrl"))
        window = (project.get("rangeStartSec") or 0.0, project["rangeEndSec"]) if project.get("rangeEndSec") is not None else (None, None)
        k = sources.key(src, *window) if src else None
        if k:
            source_cache.remember_key(folder, k)
    duration = float(info.get("duration") or 0) or float(
        (probe_json(source).get("format") or {}).get("duration") or 0)
    fields = {"durationSec": int(round(duration)), "progress": 20, "stage": "Descarga lista"}
    if info.get("title") and not project.get("title"):
        fields["title"] = str(info["title"])[:300]
    if info.get("language"):
        fields["language"] = str(info["language"]).split("-")[0]
    db.update_project(project_id, **fields)
    # Miniatura del proyecto: la de YouTube si existe en info.json, si no un cuadro.
    thumb = folder / "thumb.jpg"
    if not thumb.exists():
        try:
            run([ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", f"{min(duration * 0.2, 30):.2f}",
                 "-i", str(source), "-frames:v", "1", "-vf", "scale=480:-2", str(thumb)], what="miniatura")
            db.update_project(project_id, thumbPath=str(thumb.relative_to(settings().data_dir)))
        except Exception:
            pass


def info_summary(folder: Path) -> dict:
    info = read_json(folder / "source.info.json", {}) or {}
    return {"title": info.get("title"), "duration": info.get("duration"),
            "language": info.get("language"), "has_heatmap": bool(info.get("heatmap")),
            "chapters": len(info.get("chapters") or [])}


__all__ = ["run_task", "classify_download_error", "is_youtube_url", "info_summary"]
