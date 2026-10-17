"""API local de procesamiento (FastAPI). Escucha solo en 127.0.0.1.

    uvicorn media.main:app --host 127.0.0.1 --port 8000

Endpoints: POST /jobs · GET /files/... · además control de proyectos,
limpieza, descarga del MP4 final, plantillas, fuentes, línea de tiempo del
estudio, cancelación de renders, salud y conexión con TikTok.
Next.js (web/) es quien crea proyectos y clips en SQLite; aquí se procesan.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from media.config import settings
from media.errors import PermanentError
from media.services import ass_builder, cover, db, emoji_art, fonts, hashtags, publisher, timeline_assets
from media.services.local_guard import LocalGuard
from media.services.ffmpeg import FFmpegError, ffmpeg_bin, has_libass
from media.worker import CLIP_JOBS, PROJECT_JOBS, Worker, cancel_render, control_project

# Sin barras de progreso de Hugging Face en la terminal (la UI ya muestra el avance).
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def _setup_logging() -> None:
    logs = settings().data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(logs / "media.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.handlers = [fh, sh]
    for noisy in ("httpx", "httpcore", "urllib3", "huggingface_hub", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


worker = Worker()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _setup_logging()
    settings().projects_dir.mkdir(parents=True, exist_ok=True)
    if not settings().db_path.exists():
        logging.getLogger("media").error("No existe %s: ejecuta `npx prisma migrate deploy` en web/",
                                         settings().db_path)
    worker.start()
    yield
    worker.shutdown()


app = FastAPI(title="ClipAI media", version="1.0", lifespan=lifespan)
# Rechaza Host/Origin ajenos (CSRF y DNS rebinding); ver services/local_guard.py.
app.add_middleware(LocalGuard)
settings().projects_dir.mkdir(parents=True, exist_ok=True)
# Videos, clips y miniaturas de data/projects (StaticFiles admite Range para el <video>).
app.mount("/files/projects", StaticFiles(directory=settings().projects_dir), name="files")
# Fuentes (incluidas + subidas) para previsualizarlas en la web con @font-face.
app.mount("/files/fonts", StaticFiles(directory=fonts.fonts_dir()), name="fonts")


class JobIn(BaseModel):
    type: str
    targetId: str = Field(min_length=8, max_length=40, pattern=r"^[a-z0-9]+$")
    payload: dict = Field(default_factory=dict)


class ControlIn(BaseModel):
    action: str


class CoverIn(BaseModel):
    """Ajustes de la portada; solo cambian las claves que llegan. ``text``
    y ``time`` en null vuelven a lo automático (el gancho, el mejor cuadro)."""
    text: str | None = Field(default=None, max_length=200)
    time: float | None = Field(default=None, ge=0)
    position: str | None = Field(default=None, pattern=r"^(top|center|bottom)$")
    style: str | None = Field(default=None, pattern=r"^(outline|box)$")
    dim: bool | None = None
    reset: bool = False


def _err(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/health")
def health() -> dict:
    s = settings()
    try:
        ytdlp = __import__("yt_dlp").version.__version__
    except Exception:
        ytdlp = None
    deno = shutil.which("deno")
    counts: dict[str, int] = {}
    with db.connect() as conn:
        for row in conn.execute('SELECT status, COUNT(*) n FROM "Job" GROUP BY status'):
            counts[row["status"]] = row["n"]
    if s.llm_base_url and s.llm_model:
        llm = "openai:" + s.llm_model
    elif s.vertex_configured:
        llm = "vertex:" + s.gemini_model
    elif s.gemini_api_key:
        llm = "gemini:" + s.gemini_model
    else:
        llm = "heuristic"
    current = worker.current
    return {
        "ok": True,
        "ffmpeg": ffmpeg_bin(), "libass": has_libass(), "deno": bool(deno), "ytdlp": ytdlp,
        "llm": llm, "llmConfigured": s.llm_configured,
        "whisper": f"{s.whisper_engine}:{s.whisper_model}/{s.whisper_device}",
        "autoRender": s.auto_render,
        "clipMinSec": s.clip_min_sec, "clipMaxSec": s.clip_max_sec,
        "emoji": emoji_art.available(),
        "hashtagsBase": hashtags.base_tags(s.hashtags_base), "hashtagsCreator": s.hashtags_creator,
        "worker": {"alive": worker.is_alive(),
                   "current": {"type": current["type"], "targetId": current["targetId"]} if current else None},
        "queue": counts,
        "publishers": publisher.providers_status(),
        "diskFreeGb": round(shutil.disk_usage(s.data_dir).free / 1024 ** 3, 1),
    }


@app.post("/jobs")
def create_job(job: JobIn) -> dict:
    if job.type in PROJECT_JOBS:
        project = db.get_project(job.targetId)
        if project is None:
            raise HTTPException(404, "Proyecto no encontrado")
        if db.has_pending_job(job.type, job.targetId):
            return {"id": None, "deduplicated": True}
        if job.type == "download":
            db.update_project(job.targetId, status="QUEUED", error=None, stage="En cola")
    elif job.type in CLIP_JOBS:
        clip = db.get_clip(job.targetId)
        if clip is None:
            raise HTTPException(404, "Clip no encontrado")
        if db.has_pending_job(job.type, job.targetId):
            # Un render ya en cola usará la versión más reciente del clip al ejecutarse.
            return {"id": None, "deduplicated": True}
        if job.type == "render":
            db.update_clip(job.targetId, renderStatus="QUEUED", renderError=None)
        else:
            db.update_clip(job.targetId, publishStatus="QUEUED", publishInfo=None)
    else:
        raise HTTPException(400, f"Tipo de job desconocido: {job.type}")
    job_id = db.enqueue_job(job.type, job.targetId, job.payload)
    worker.wake()
    return {"id": job_id}


@app.post("/projects/{project_id}/control")
def project_control(project_id: str, body: ControlIn) -> dict:
    try:
        return control_project(worker, project_id, body.action)
    except PermanentError as exc:
        raise _err(exc, 404 if "no existe" in str(exc) else 400)


def _has_pending_renders(project_id: str) -> bool:
    return any(db.has_pending_job("render", c["id"]) for c in db.list_clips(project_id))


def _cleanup_project(project: dict) -> int:
    """«Limpiar»: borra source.mp4 y audio.wav (los trozos de cada clip se
    conservan para poder re-renderizar)."""
    folder = settings().projects_dir / project["id"]
    freed = 0
    for name in ("source.mp4", "audio.wav"):
        f = folder / name
        if f.exists():
            freed += f.stat().st_size
            f.unlink()
    db.update_project(project["id"], sourceDeleted=True)
    return freed


@app.post("/projects/{project_id}/cleanup")
def cleanup_project(project_id: str) -> dict:
    project = db.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Proyecto no encontrado")
    if project["status"] not in ("READY", "STOPPED", "FAILED"):
        raise HTTPException(409, "Solo se limpian proyectos terminados")
    if _has_pending_renders(project_id) or worker.current_project == project_id:
        raise HTTPException(409, "Espera a que terminen sus renders antes de limpiar")
    return {"freedMb": round(_cleanup_project(project) / 1024 ** 2, 1)}


@app.post("/cleanup")
def cleanup_all() -> dict:
    freed, n = 0, 0
    for p in db.list_projects():
        if p["status"] in ("READY", "STOPPED", "FAILED") and not p["sourceDeleted"]:
            if worker.current_project == p["id"] or _has_pending_renders(p["id"]):
                continue
            freed += _cleanup_project(p)
            n += 1
    return {"projects": n, "freedMb": round(freed / 1024 ** 2, 1)}


def _safe_filename(title: str) -> str:
    base = re.sub(r"#\w+", "", title or "clip")
    base = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑüÜ¿?¡!]", "", base).strip()
    base = re.sub(r"[\s]+", " ", base)[:80].strip() or "clip"
    return base.replace("?", "").replace("¿", "").replace("!", "").replace("¡", "") + ".mp4"


def _download_base(name: str | None) -> str | None:
    """Nombre base que manda la web («03 - ¡Le trajo un conejo! 🐰»; el mismo
    para el video y su portada): con sus emojis y signos, sin lo que los
    sistemas de archivos no aceptan (separadores de ruta, ``: * ? " < > |``)."""
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name or "")
    base = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufe0e\ufe0f\ufeff]", "", base)
    base = re.sub(r"\s+", " ", base).strip(" .-")[:100].strip(" .-")
    return base or None


def _data_file(rel: str):
    """Archivo dentro de ``data/``; 404 si no existe o si la ruta guardada se sale de ahí."""
    root = settings().data_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return path


@app.get("/download/clip/{clip_id}")
def download_clip(clip_id: str, name: str | None = None):
    clip = db.get_clip(clip_id)
    if clip is None or not clip.get("outputPath"):
        raise HTTPException(404, "El clip no está renderizado")
    path = _data_file(clip["outputPath"])
    base = _download_base(name)
    return FileResponse(path, media_type="video/mp4",
                        filename=f"{base}.mp4" if base else _safe_filename(clip.get("hook") or clip["title"]))


@app.post("/clips/{clip_id}/cover")
def clip_cover(clip_id: str, body: CoverIn) -> dict:
    """Guarda los ajustes de la portada y la vuelve a generar (≈ 0,5 s; el
    primer cuadro automático tarda unos segundos más)."""
    import json as _json

    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip no encontrado")
    patch = {k: getattr(body, k) for k in body.model_fields_set if k in cover.DEFAULTS}
    wanted = cover.parse(None) if body.reset else cover.merge(clip.get("cover"), patch)
    cfolder = settings().projects_dir / clip["projectId"] / "clips" / clip_id
    try:
        made = cover.make_cover({**clip, "cover": wanted}, cfolder)
    except cover.CoverError as exc:
        raise HTTPException(409, str(exc)) from exc
    except FFmpegError as exc:
        logging.getLogger("media").warning("portada de %s: %s", clip_id, exc)
        raise HTTPException(500, "No se pudo generar la portada (ffmpeg). Revisa logs/media.log.") from exc
    rel = str(made["path"].resolve().relative_to(settings().data_dir.resolve()))
    db.update_clip(clip_id, cover=_json.dumps(wanted, ensure_ascii=False), coverPath=rel)
    return {"coverPath": rel, "cover": wanted, "time": made["time"], "auto": made["auto"]}


@app.get("/download/cover/{clip_id}")
def download_cover(clip_id: str, name: str | None = None):
    clip = db.get_clip(clip_id)
    if clip is None or not clip.get("coverPath"):
        raise HTTPException(404, "El clip aún no tiene portada")
    path = _data_file(clip["coverPath"])
    base = _download_base(name)
    return FileResponse(path, media_type="image/jpeg",
                        filename=cover.filename(clip, base))


@app.get("/source-info")
def source_info(url: str, tab: str = "videos") -> dict:
    """Comprueba el enlace de un nuevo proyecto antes de crearlo: de un VOD de
    Kick devuelve título, canal y duración (o dice que ya no existe: Kick los
    borra a los pocos días); de un canal de Kick, sus VODs disponibles; de un
    canal de YouTube, sus videos (``tab``: videos | streams)."""
    from media.services import sources

    src = sources.parse(url)
    if src is None:
        raise HTTPException(400, "Pega el enlace de un video de YouTube o de un VOD de Kick.")
    try:
        if src["type"] == "kick" and src["kind"] == "video":
            return sources.info(url, settings().max_video_minutes)
        if src["type"] == "kick" and src["kind"] == "channel":
            return {"type": "kick", "kind": "channel", **sources.kick_channel_vods(src["id"])}
        if src["type"] == "youtube" and src["kind"] == "channel":
            return {"type": "youtube", "kind": "channel",
                    **sources.youtube_channel_videos(src["id"], tab, settings().max_video_minutes)}
    except sources.SourceError as exc:
        raise HTTPException(404 if sources.GONE in str(exc) or "No existe el canal" in str(exc) else 502, str(exc)) from exc
    if src["type"] == "kick":
        raise HTTPException(400, "Es un clip de Kick (dura menos de un minuto). Pega el VOD (kick.com/canal/videos/…) o el canal.")
    return {"type": "youtube", "kind": src["kind"], "id": src["id"]}


@app.get("/trending")
def trending(q: str = "", period: str = "week", sort: str = "views", duration: str = "long", limit: int = 24,
             refresh: bool = False, lang: str = "auto") -> dict:
    """Videos de YouTube con potencial para clips (services/trending.py). Sin
    ``q`` busca los temas de TRENDING_TOPICS. Tarda unos segundos la primera
    vez (lee la ficha de cada candidato); después sale de la caché (30 min)."""
    from media.services import trending as tr

    if period not in tr.PERIODS or sort not in tr.SORTS or duration not in (*tr.DURATIONS, "any"):
        raise HTTPException(400, "Periodo, orden o duración no válidos")
    try:
        out = tr.discover(q, period=period, sort=sort, duration=None if duration == "any" else duration,
                          limit=max(1, min(48, limit)), refresh=refresh, lang=lang)
    except tr.TrendingError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {**out, "topics": tr.default_topics(), "defaultLang": tr.resolve_lang("auto")}


@app.get("/templates")
def templates() -> list[dict]:
    return ass_builder.list_templates()


@app.post("/clips/{clip_id}/cancel-render")
def clip_cancel_render(clip_id: str) -> dict:
    try:
        return cancel_render(worker, clip_id)
    except PermanentError as exc:
        raise _err(exc, 404)


@app.get("/clips/{clip_id}/timeline")
def clip_timeline(clip_id: str, start: float, end: float) -> dict:
    """Miniaturas y forma de onda del video fuente entre start y end."""
    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip no encontrado")
    project = db.get_project(clip["projectId"])
    folder = settings().projects_dir / clip["projectId"]
    if project is None or not (folder / "source.mp4").exists():
        raise HTTPException(409, "El video fuente se borró con «Limpiar»: no hay línea de tiempo.")
    if not (0 <= start < end) or end - start > 3 * 3600:
        raise HTTPException(400, "Rango inválido")
    cfolder = folder / "clips" / clip_id
    cfolder.mkdir(parents=True, exist_ok=True)
    data = timeline_assets.build(folder, cfolder, start, end, float(project.get("durationSec") or 0))
    data["thumbs"] = f"projects/{clip['projectId']}/clips/{clip_id}/{data['thumbs']}"
    return data


class PublishTextIn(BaseModel):
    hook: str | None = Field(None, max_length=300)
    hashtags: str | None = Field(None, max_length=600)


@app.post("/clips/{clip_id}/publish-text")
def publish_text_for(clip_id: str, body: PublishTextIn) -> dict:
    """Título, descripción y hashtags para publicar (con el creador del video original). ``hook`` y
    ``hashtags`` opcionales: lo que se está editando en el estudio y todavía no se guardó."""
    from media.tasks.publish import post_text

    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "El clip no existe.")
    return post_text(clip, body.hook, body.hashtags)


@app.post("/clips/{clip_id}/hashtags")
def clip_hashtags(clip_id: str) -> dict:
    """Vuelve a sugerir los hashtags por red con lo que dice el clip AHORA
    (sus tramos editados y sus palabras corregidas)."""
    import json as _json
    from collections import Counter

    from media.services import edit_doc, texttiling_ops
    from media.services.atomic import read_json
    from media.services.llm import LLM, LLMError
    from media.tasks.analyze import channel_tags

    clip = db.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip no encontrado")
    project = db.get_project(clip["projectId"]) or {}
    folder = settings().projects_dir / clip["projectId"]
    caps = read_json(folder / "clips" / clip_id / "captions.json", {}) or {}
    parts = edit_doc.clip_parts(clip)
    text = " ".join(w["w"] for a, b in parts for w in caps.get("words") or []
                    if a <= (w["start"] + w["end"]) / 2 < b and str(w.get("w", "")).strip())
    if not text:
        raise HTTPException(409, "El clip no tiene palabras para sugerir hashtags.")
    language = project.get("language") or "es"
    transcript = read_json(folder / "transcript.json", {}) or {}
    all_counts = Counter(texttiling_ops.tokenize(" ".join(w["w"] for w in transcript.get("words") or [])))
    fallback = hashtags.heuristic_sets(text, all_counts, language)
    video = hashtags.video_label(read_json(folder / "source.info.json", {}), project.get("title"))
    sets, source = fallback, "heuristic"
    llm = LLM()
    if llm.available:
        try:
            got = llm.generate_list(hashtags.build_prompt(text, clip.get("hook") or clip.get("title") or "", clip.get("hook") or "",
                                                          language, video), hashtags.HashtagSets)
            sets = hashtags.complete(hashtags.clean_sets(got[0], language), fallback)
            source = "llm"
        except LLMError as exc:
            logging.getLogger("media").warning("hashtags con IA fallaron; uso el respaldo: %s", exc)
        finally:
            db.add_ai_usage(clip["projectId"], llm.usage)
    sets = hashtags.apply_niche(sets, *channel_tags(folder), prefer=video)
    db.update_clip(clip_id, hashtagSets=_json.dumps(sets, ensure_ascii=False))
    return {**sets, "source": source}


@app.get("/fonts")
def list_fonts() -> list[dict]:
    return fonts.list_fonts()


@app.post("/fonts")
async def upload_font(request: Request, name: str) -> dict:
    if int(request.headers.get("content-length") or 0) > fonts.MAX_BYTES:
        raise HTTPException(413, "La fuente pesa más de 15 MB.")
    data = await request.body()
    try:
        return fonts.add_font(name, data)
    except fonts.FontError as exc:
        raise _err(exc)


@app.delete("/fonts/{file}")
def delete_font(file: str) -> dict:
    try:
        fonts.delete_font(file)
    except fonts.FontError as exc:
        raise _err(exc, 404 if "no existe" in str(exc) else 400)
    return {"ok": True}
