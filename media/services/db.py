"""Acceso a data/app.db desde Python (sqlite3, modo WAL).

El esquema lo crea Prisma (web/prisma/migrations). Aquí solo se leen y
escriben filas. Reglas para convivir con Prisma 7 (adaptador better-sqlite3):

* DateTime en ISO 8601 con milisegundos y `+00:00` (el formato que escribe
  Prisma); ver `now_iso()`.
* Boolean como INTEGER 0/1.
* Los ids se generan aquí con el mismo alfabeto que cuid (minúsculas y dígitos).

Cada operación abre su propia conexión: SQLite es barato de abrir y así el
hilo de trabajo y los hilos de FastAPI nunca comparten una conexión.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import string
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from media.config import settings

_BASE36 = string.digits + string.ascii_lowercase

PROJECT_ACTIVE = ("QUEUED", "UPLOADING", "DOWNLOADING", "TRANSCRIBING", "ANALYZING")


def now_iso(delta_seconds: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return dt.isoformat(timespec="milliseconds")


def new_id() -> str:
    """Id tipo cuid: 'c' + tiempo en base36 + 16 caracteres aleatorios."""
    n, ts = int(time.time() * 1000), ""
    while n:
        n, r = divmod(n, 36)
        ts = _BASE36[r] + ts
    return "c" + ts + "".join(secrets.choice(_BASE36) for _ in range(16))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = settings().db_path
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


def _prep(value: Any) -> Any:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _update(table: str, row_id: str, fields: dict) -> None:
    if not fields:
        return
    fields = {**fields, "updatedAt": now_iso()}
    cols = ", ".join(f'"{k}" = ?' for k in fields)
    with connect() as conn:
        conn.execute(f'UPDATE "{table}" SET {cols} WHERE id = ?',
                     [*(_prep(v) for v in fields.values()), row_id])


# ── Project ──────────────────────────────────────────────────────────────────

def get_project(project_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute('SELECT * FROM "Project" WHERE id = ?', [project_id]).fetchone())


def update_project(project_id: str, **fields: Any) -> None:
    _update("Project", project_id, fields)


def list_projects() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM "Project" ORDER BY createdAt DESC')]


def add_ai_usage(project_id: str, usage: dict | None) -> None:
    """Suma tokens y costo estimado de IA al proyecto (análisis, ganchos…)."""
    if not usage or not usage.get("calls"):
        return
    tokens = int(usage.get("prompt_tokens", 0)) + int(usage.get("output_tokens", 0)) + \
        int(usage.get("thinking_tokens", 0))
    with connect() as conn:
        conn.execute('UPDATE "Project" SET aiCostUsd = aiCostUsd + ?, aiTokens = aiTokens + ?, '
                     'aiCostEstimated = MAX(aiCostEstimated, ?), updatedAt = ? WHERE id = ?',
                     [float(usage.get("cost_usd", 0.0)), tokens, 1 if usage.get("estimated") else 0,
                      now_iso(), project_id])


def delete_project(project_id: str) -> None:
    with connect() as conn:
        conn.execute('DELETE FROM "Project" WHERE id = ?', [project_id])


# ── Clip ─────────────────────────────────────────────────────────────────────

CLIP_INSERT_FIELDS = (
    "rank", "startSec", "endSec", "score", "reason", "hook", "hookType", "title", "description",
    "hashtags", "hashtagSets", "templateId", "captionsPath", "topic", "bestLine", "bestLineStart",
    "bestLineEnd", "prependBestLine", "signals", "layoutMode", "edit",
)


def insert_clip(project_id: str, clip: dict) -> str:
    clip_id = clip.get("id") or new_id()
    now = now_iso()
    data = {k: _prep(clip[k]) for k in CLIP_INSERT_FIELDS if k in clip}
    data.update(id=clip_id, projectId=project_id, createdAt=now, updatedAt=now)
    cols = ", ".join(f'"{k}"' for k in data)
    marks = ", ".join("?" for _ in data)
    with connect() as conn:
        conn.execute(f'INSERT INTO "Clip" ({cols}) VALUES ({marks})', list(data.values()))
    return clip_id


def get_clip(clip_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute('SELECT * FROM "Clip" WHERE id = ?', [clip_id]).fetchone())


def list_clips(project_id: str) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM "Clip" WHERE projectId = ? ORDER BY rank ASC, score DESC', [project_id])]


def update_clip(clip_id: str, **fields: Any) -> None:
    _update("Clip", clip_id, fields)


def delete_clips(project_id: str) -> None:
    with connect() as conn:
        conn.execute('DELETE FROM "Clip" WHERE projectId = ?', [project_id])


# ── Job ──────────────────────────────────────────────────────────────────────

def enqueue_job(job_type: str, target_id: str, payload: dict | None = None,
                run_after: str | None = None) -> str:
    job_id = new_id()
    now = now_iso()
    with connect() as conn:
        conn.execute(
            'INSERT INTO "Job" (id, type, targetId, status, attempts, payload, runAfter, createdAt, updatedAt) '
            "VALUES (?, ?, ?, 'QUEUED', 0, ?, ?, ?, ?)",
            [job_id, job_type, target_id, json.dumps(payload or {}), run_after, now, now],
        )
    return job_id


def get_job(job_id: str) -> dict | None:
    with connect() as conn:
        return _row(conn.execute('SELECT * FROM "Job" WHERE id = ?', [job_id]).fetchone())


def list_jobs(target_ids: list[str] | None = None, statuses: tuple[str, ...] | None = None) -> list[dict]:
    q, args = 'SELECT * FROM "Job" WHERE 1=1', []
    if target_ids is not None:
        if not target_ids:
            return []
        q += f" AND targetId IN ({', '.join('?' for _ in target_ids)})"
        args += target_ids
    if statuses:
        q += f" AND status IN ({', '.join('?' for _ in statuses)})"
        args += list(statuses)
    with connect() as conn:
        return [dict(r) for r in conn.execute(q + " ORDER BY createdAt ASC", args)]


def queued_jobs() -> list[dict]:
    """Jobs listos para correr (sin espera pendiente), en orden de llegada."""
    now = now_iso()
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM \"Job\" WHERE status = 'QUEUED' AND (runAfter IS NULL OR runAfter <= ?) "
            "ORDER BY createdAt ASC", [now])]


def claim_job(job_id: str) -> bool:
    """QUEUED → RUNNING de forma atómica (evita correr dos veces el mismo job)."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE \"Job\" SET status = 'RUNNING', attempts = attempts + 1, updatedAt = ? "
            "WHERE id = ? AND status = 'QUEUED'", [now_iso(), job_id])
        return cur.rowcount == 1


def finish_job(job_id: str) -> None:
    _update("Job", job_id, {"status": "DONE", "error": None})


def fail_job(job_id: str, error: str, retry_in: float | None = None) -> None:
    if retry_in is None:
        _update("Job", job_id, {"status": "FAILED", "error": error[:4000]})
    else:
        _update("Job", job_id, {"status": "QUEUED", "error": error[:4000],
                                "runAfter": now_iso(retry_in)})


def cancel_jobs(target_ids: list[str]) -> int:
    if not target_ids:
        return 0
    marks = ", ".join("?" for _ in target_ids)
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE \"Job\" SET status = 'CANCELLED', updatedAt = ? "
            f"WHERE targetId IN ({marks}) AND status IN ('QUEUED')", [now_iso(), *target_ids])
        return cur.rowcount


def cancel_jobs_of_type(job_type: str, target_id: str) -> int:
    """Cancela los jobs EN COLA de un tipo para un objetivo."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE \"Job\" SET status = 'CANCELLED', updatedAt = ? "
            "WHERE type = ? AND targetId = ? AND status = 'QUEUED'", [now_iso(), job_type, target_id])
        return cur.rowcount


def requeue_running_jobs() -> int:
    """Al arrancar: los jobs que quedaron RUNNING (corte, reinicio) vuelven a la cola."""
    with connect() as conn:
        cur = conn.execute("UPDATE \"Job\" SET status = 'QUEUED', updatedAt = ? WHERE status = 'RUNNING'",
                           [now_iso()])
        return cur.rowcount


def has_pending_job(job_type: str, target_id: str) -> bool:
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM \"Job\" WHERE type = ? AND targetId = ? AND status IN ('QUEUED', 'RUNNING') LIMIT 1",
            [job_type, target_id]).fetchone() is not None


def requeue_job(job_id: str) -> None:
    """De vuelta a la cola sin gastar intento (pausa del usuario)."""
    with connect() as conn:
        conn.execute("UPDATE \"Job\" SET status = 'QUEUED', attempts = MAX(0, attempts - 1), updatedAt = ? "
                     "WHERE id = ?", [now_iso(), job_id])


def reschedule_job(job_id: str, run_after: str, note: str = "") -> None:
    """Reprograma (p. ej. límite diario del proveedor) sin gastar intento."""
    with connect() as conn:
        conn.execute("UPDATE \"Job\" SET status = 'QUEUED', attempts = MAX(0, attempts - 1), runAfter = ?, "
                     "error = ?, updatedAt = ? WHERE id = ?", [run_after, note[:1000], now_iso(), job_id])


def cancel_job(job_id: str) -> None:
    _update("Job", job_id, {"status": "CANCELLED"})
