"""Cola local: un único hilo de trabajo sobre la tabla Job de SQLite (plan 2 y 6.8).

* Un job a la vez, en orden de llegada; `runAfter` permite esperas.
* Fases de proyecto encadenadas: download → transcribe → analyze. Cada tarea
  reutiliza lo ya hecho (puntos de control en disco).
* Reintentos acotados: hasta 3 con espera creciente; `PermanentError` no se
  reintenta; `RateLimited` reprograma sin gastar intento (p. ej. al día siguiente).
* Al arrancar, los jobs RUNNING vuelven a QUEUED.
* Pausar deja los jobs del proyecto en espera; detener los cancela conservando
  lo hecho; descartar además borra la carpeta cuando el job en curso termina.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import traceback

from media.config import settings
from media.errors import PermanentError, RateLimited, StopRequested
from media.services import db

log = logging.getLogger("media.worker")

MAX_ATTEMPTS = 3
PROJECT_JOBS = ("download", "transcribe", "analyze")
CLIP_JOBS = ("render", "tiktok_draft", "publish")
NEXT_PHASE = {"download": "transcribe", "transcribe": "analyze"}
PHASE_STATUS = {"download": "DOWNLOADING", "transcribe": "TRANSCRIBING", "analyze": "ANALYZING"}


def _handlers():
    from media.tasks import analyze, download, render, transcribe
    handlers = {
        "download": download.run_task,
        "transcribe": transcribe.run_task,
        "analyze": analyze.run_task,
        "render": render.run_task,
    }
    try:
        from media.tasks import publish
        handlers.update(tiktok_draft=publish.run_tiktok_draft, publish=publish.run_publish)
    except ImportError:  # publicación opcional
        pass
    return handlers


def backoff(attempt: int) -> float:
    """1.º reintento a los 15 s, 2.º a los 60 s."""
    return 15.0 * (4 ** max(0, attempt - 1))


def project_of(job: dict) -> str | None:
    if job["type"] in PROJECT_JOBS:
        return job["targetId"]
    clip = db.get_clip(job["targetId"])
    return clip["projectId"] if clip else None


class Worker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="clipai-worker", daemon=True)
        self._wake = threading.Event()
        self._stop_flag = threading.Event()
        self.current: dict | None = None
        self.current_project: str | None = None
        self.pending_deletes: set[str] = set()
        self._lock = threading.Lock()
        self.handlers = None

    # ── API para FastAPI ─────────────────────────────────────────────────────
    def wake(self) -> None:
        self._wake.set()

    def shutdown(self) -> None:
        self._stop_flag.set()
        self._wake.set()

    def delete_project_files(self, project_id: str) -> None:
        """Borra la carpeta ahora o, si el job en curso la usa, al terminarlo."""
        with self._lock:
            if self.current_project == project_id:
                self.pending_deletes.add(project_id)
                return
        shutil.rmtree(settings().projects_dir / project_id, ignore_errors=True)

    # ── Bucle ────────────────────────────────────────────────────────────────
    def run(self) -> None:
        n = db.requeue_running_jobs()
        if n:
            log.info("%d job(s) interrumpidos vuelven a la cola", n)
        # Proyectos que quedaron a medio camino tras un corte: su job ya está QUEUED.
        if self.handlers is None:
            self.handlers = _handlers()
        while not self._stop_flag.is_set():
            try:
                job = self._next_job()
            except Exception:
                log.exception("error leyendo la cola")
                job = None
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._execute(job)

    def _next_job(self) -> dict | None:
        for job in db.queued_jobs():
            pid = project_of(job)
            if pid is None:
                db.fail_job(job["id"], "el proyecto o clip ya no existe")
                continue
            project = db.get_project(pid)
            if project is None:
                db.fail_job(job["id"], "el proyecto ya no existe")
                continue
            if project["status"] == "PAUSED":
                continue
            if project["status"] == "STOPPED" and job["type"] in PROJECT_JOBS:
                db.cancel_jobs([job["targetId"]])
                continue
            if db.claim_job(job["id"]):
                return db.get_job(job["id"])
        return None

    def _execute(self, job: dict) -> None:
        pid = project_of(job)
        with self._lock:
            self.current, self.current_project = job, pid
        payload = json.loads(job.get("payload") or "{}")
        kind, target = job["type"], job["targetId"]
        log.info("▶ %s %s (intento %d)", kind, target, job["attempts"])
        t0 = time.time()
        try:
            handler = self.handlers.get(kind)
            if handler is None:
                raise PermanentError(f"No hay manejador para jobs de tipo {kind}")
            handler(target, payload)
        except StopRequested as exc:
            self._on_stop(job, pid, str(exc))
        except RateLimited as exc:
            log.warning("límite diario del proveedor; se reprograma: %s", exc)
            db.reschedule_job(job["id"], exc.retry_at, note=str(exc))
            if kind in CLIP_JOBS:
                db.update_clip(target, publishStatus="SCHEDULED",
                               publishInfo=json.dumps({"note": str(exc), "retryAt": exc.retry_at}))
        except PermanentError as exc:
            log.warning("✖ %s %s: %s", kind, target, exc)
            db.fail_job(job["id"], str(exc))
            self._mark_failed(kind, target, str(exc))
        except Exception as exc:  # transitorio: reintentar con espera creciente
            detail = f"{type(exc).__name__}: {exc}"
            log.error("✖ %s %s: %s\n%s", kind, target, detail, traceback.format_exc())
            if job["attempts"] < MAX_ATTEMPTS:
                wait = backoff(job["attempts"])
                db.fail_job(job["id"], detail, retry_in=wait)
                if kind in PROJECT_JOBS:
                    db.update_project(target, stage=f"Error, reintento {job['attempts']}/{MAX_ATTEMPTS - 1} "
                                                    f"en {int(wait)} s: {str(exc)[:160]}")
                elif kind == "render":
                    db.update_clip(target, renderStatus="QUEUED",
                                   renderError=f"Reintento en {int(wait)} s: {str(exc)[:300]}")
            else:
                db.fail_job(job["id"], detail)
                self._mark_failed(kind, target, detail)
        else:
            db.finish_job(job["id"])
            log.info("✔ %s %s en %.1f s", kind, target, time.time() - t0)
            nxt = NEXT_PHASE.get(kind)
            if nxt:
                p = db.get_project(target)
                if p and p["status"] not in ("PAUSED", "STOPPED"):
                    db.enqueue_job(nxt, target, payload)
        finally:
            with self._lock:
                self.current, self.current_project = None, None
                deletes = [p for p in self.pending_deletes if p == pid]
                self.pending_deletes.difference_update(deletes)
            for p in deletes:
                shutil.rmtree(settings().projects_dir / p, ignore_errors=True)

    def _on_stop(self, job: dict, pid: str | None, reason: str) -> None:
        project = db.get_project(pid) if pid else None
        if project and project["status"] == "PAUSED":
            db.requeue_job(job["id"])  # se retoma al reanudar, sin gastar intento
            log.info("⏸ %s %s en pausa", job["type"], job["targetId"])
            return
        db.cancel_job(job["id"])
        if job["type"] == "render":
            db.update_clip(job["targetId"], renderStatus="NONE")
        log.info("⏹ %s %s detenido (%s)", job["type"], job["targetId"], reason)

    @staticmethod
    def _mark_failed(kind: str, target: str, message: str) -> None:
        if kind in PROJECT_JOBS:
            db.update_project(target, status="FAILED", error=message[:2000], stage=f"Falló: {kind}")
        elif kind == "render":
            db.update_clip(target, renderStatus="FAILED", renderError=message[:2000])
        else:
            db.update_clip(target, publishStatus="FAILED", publishInfo=json.dumps({"error": message[:1000]}))


def control_project(worker: Worker, project_id: str, action: str) -> dict:
    """pause | resume | stop | discard | retry | reanalyze."""
    project = db.get_project(project_id)
    if project is None:
        raise PermanentError("El proyecto no existe.")
    clip_ids = [c["id"] for c in db.list_clips(project_id)]
    if action == "pause":
        # Un proyecto READY también se pausa si tiene renders o envíos en cola.
        pending_clip_jobs = any(db.has_pending_job(t, cid) for t in CLIP_JOBS for cid in clip_ids)
        if project["status"] in ("FAILED", "STOPPED") or (project["status"] == "READY" and not pending_clip_jobs):
            return {"status": project["status"]}
        db.update_project(project_id, status="PAUSED", stage="En pausa")
    elif action == "resume":
        if project["status"] == "PAUSED":
            phase_pending = any(db.has_pending_job(t, project_id) for t in PROJECT_JOBS)
            status = "QUEUED" if phase_pending or not clip_ids else "READY"
            db.update_project(project_id, status=status, stage="Reanudado")
    elif action == "stop":
        db.cancel_jobs([project_id, *clip_ids])
        for cid in clip_ids:
            c = db.get_clip(cid)
            if c and c["renderStatus"] == "QUEUED":
                db.update_clip(cid, renderStatus="NONE")
        status = "READY" if clip_ids and project["status"] in ("READY", "PAUSED") else "STOPPED"
        db.update_project(project_id, status=status, stage="Detenido; se conserva lo hecho")
    elif action == "discard":
        db.cancel_jobs([project_id, *clip_ids])
        db.update_project(project_id, status="STOPPED")
        db.delete_project(project_id)
        worker.delete_project_files(project_id)
    elif action in ("retry", "reanalyze"):
        if db.has_pending_job("download", project_id) or db.has_pending_job("transcribe", project_id) \
                or db.has_pending_job("analyze", project_id):
            return {"status": project["status"]}
        db.update_project(project_id, status="QUEUED", error=None, progress=0 if action == "retry" else 60,
                          stage="En cola")
        if action == "reanalyze":
            db.enqueue_job("analyze", project_id, {"force": True})
        else:
            db.enqueue_job("download", project_id, {})
    else:
        raise PermanentError(f"Acción desconocida: {action}")
    worker.wake()
    p = db.get_project(project_id)
    return {"status": p["status"] if p else "DELETED"}
