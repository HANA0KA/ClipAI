"""Errores de la cola de trabajo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class PermanentError(RuntimeError):
    """Error que no se arregla reintentando: URL inválida, video privado,
    revisión previa fallida. El job pasa a FAILED sin más intentos."""


class StopRequested(RuntimeError):
    """El usuario pausó, detuvo o descartó el proyecto durante la tarea."""


def next_day_iso(hour: int = 0, minute: int = 5) -> str:
    """Mañana a las 00:05 hora local, expresado en UTC ISO 8601 (formato de la
    BD: las comparaciones de `runAfter` son de texto y exigen el mismo huso)."""
    now = datetime.now().astimezone()
    tomorrow = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class RateLimited(RuntimeError):
    """Un proveedor alcanzó su tope diario; la cola reprograma el job para
    ``retry_at`` (ISO 8601 UTC) sin gastar un intento."""

    def __init__(self, message: str, retry_at: str | None = None):
        super().__init__(message)
        self.retry_at = retry_at or next_day_iso()
