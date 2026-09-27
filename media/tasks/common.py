"""Ayudas compartidas por las tareas: carpetas, progreso y control de parada."""
from __future__ import annotations

import logging
from pathlib import Path

from media.config import settings
from media.errors import PermanentError, StopRequested
from media.services import db

log = logging.getLogger("media.tasks")


def project_folder(project_id: str) -> Path:
    folder = settings().projects_dir / project_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clip_folder(project_id: str, clip_id: str) -> Path:
    folder = project_folder(project_id) / "clips" / clip_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def require_project(project_id: str) -> dict:
    p = db.get_project(project_id)
    if p is None:
        raise PermanentError("El proyecto ya no existe.")
    return p


def check_stop(project_id: str) -> None:
    """Punto de parada cooperativo entre pasos largos."""
    p = db.get_project(project_id)
    if p is None or p["status"] in ("PAUSED", "STOPPED"):
        raise StopRequested(p["status"] if p else "DELETED")


def progress(project_id: str, value: float, status: str | None = None, stage: str | None = None) -> None:
    fields: dict = {"progress": int(max(0, min(100, round(value))))}
    if status:
        fields["status"] = status
    if stage is not None:
        fields["stage"] = stage
    db.update_project(project_id, **fields)
