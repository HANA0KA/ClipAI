"""Estilo de subtítulos de cada proyecto.

Todos los clips de un proyecto salen con la misma plantilla (coherencia
dentro de un video) y cada proyecto nuevo con una distinta a la de los
últimos, para que no todos los clips del canal se vean iguales. La que
elijas al crear el proyecto (o después, en la vista del proyecto) manda;
en el estudio se sigue pudiendo cambiar la de cada clip.

``Project.templateId``: None = automático (se resuelve y se guarda en el
primer análisis; «Volver a buscar momentos» conserva el mismo).
"""
from __future__ import annotations

import hashlib


def pick(available: list[str], recent: list[str], seed: str, allowed: list[str] | None = None) -> str | None:
    """Plantilla para un proyecto nuevo: la que lleva más tiempo sin usarse
    entre los proyectos recientes (``recent``, del más nuevo al más viejo);
    los empates se deciden con ``seed`` (el id del proyecto) para variar."""
    pool = [t for t in available if not allowed or t in allowed] or list(available)
    if not pool:
        return None
    last_use = {}
    for i, t in enumerate(recent):
        last_use.setdefault(t, i)
    never = len(recent) + 1
    best = max(last_use.get(t, never) for t in pool)
    ties = sorted(t for t in pool if last_use.get(t, never) == best)
    return ties[int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(ties)]


def resolve(project: dict) -> str:
    """Plantilla del proyecto: la guardada o una automática (que se guarda)."""
    from media.config import settings
    from media.services import ass_builder, db

    available = [t["id"] for t in ass_builder.list_templates()]
    chosen = project.get("templateId")
    if chosen in available:
        return chosen
    recent = [p["templateId"] for p in db.list_projects() if p["id"] != project["id"] and p.get("templateId")]
    allowed = [x.strip() for x in settings().subtitle_templates_auto.split(",") if x.strip()]
    chosen = pick(available, recent, project["id"], allowed) or ass_builder.DEFAULT_TEMPLATE
    db.update_project(project["id"], templateId=chosen)
    return chosen


__all__ = ["pick", "resolve"]
