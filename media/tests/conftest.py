"""Fixtures comunes: BD temporal creada con las migraciones de Prisma."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from media.config import ROOT_DIR, reset_settings

MIGRATIONS = ROOT_DIR / "web" / "prisma" / "migrations"


def apply_migrations(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for sql in sorted(MIGRATIONS.glob("*/migration.sql")):
            conn.executescript(sql.read_text(encoding="utf-8"))
    finally:
        conn.close()


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    db_path = data / "app.db"
    apply_migrations(db_path)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"file:{db_path}")
    reset_settings()
    yield db_path
    reset_settings()
