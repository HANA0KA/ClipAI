"""API local de procesamiento (FastAPI). Escucha solo en 127.0.0.1.

    uvicorn media.main:app --host 127.0.0.1 --port 8000

Endpoints (plan 7): POST /jobs · GET /files/... · además control de proyectos,
limpieza, descarga del MP4 final, plantillas, salud y conexión con TikTok.
Next.js (web/) es quien crea proyectos y clips en SQLite; aquí se procesan.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from media.config import settings
from media.errors import PermanentError
from media.services import ass_builder, db, publisher
from media.services.ffmpeg import ffmpeg_bin, has_libass
from media.worker import CLIP_JOBS, PROJECT_JOBS, Worker, control_project

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
settings().projects_dir.mkdir(parents=True, exist_ok=True)
# Videos, clips y miniaturas de data/projects (StaticFiles admite Range para el <video>).
app.mount("/files/projects", StaticFiles(directory=settings().projects_dir), name="files")


class JobIn(BaseModel):
    type: str
    targetId: str = Field(min_length=8, max_length=40, pattern=r"^[a-z0-9]+$")
    payload: dict = Field(default_factory=dict)


class ControlIn(BaseModel):
    action: str


class TikTokCodeIn(BaseModel):
    code: str
    state: str


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


@app.get("/download/clip/{clip_id}")
def download_clip(clip_id: str):
    clip = db.get_clip(clip_id)
    if clip is None or not clip.get("outputPath"):
        raise HTTPException(404, "El clip no está renderizado")
    path = settings().data_dir / clip["outputPath"]
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(path, media_type="video/mp4", filename=_safe_filename(clip["title"]))


@app.get("/templates")
def templates() -> list[dict]:
    return ass_builder.list_templates()


@app.get("/tiktok/auth-url")
def tiktok_auth_url() -> dict:
    try:
        return {"url": publisher.tiktok_auth_url()}
    except publisher.PublishError as exc:
        raise _err(exc)


@app.post("/tiktok/token")
def tiktok_token(body: TikTokCodeIn) -> dict:
    try:
        return publisher.tiktok_exchange_code(body.code, body.state)
    except publisher.PublishError as exc:
        raise _err(exc)


@app.get("/logs")
def logs(lines: int = 200) -> dict:
    path = settings().data_dir / "logs" / "media.log"
    if not path.exists():
        return {"lines": []}
    out = subprocess.run(["tail", "-n", str(max(1, min(lines, 2000))), str(path)],
                         capture_output=True, text=True).stdout
    return {"lines": out.splitlines()}


__all__ = ["app"]
