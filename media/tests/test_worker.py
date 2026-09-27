"""Cola: encadenado de fases, reintentos, error permanente, pausa y límites."""
import json

import pytest

from media.errors import PermanentError, RateLimited, StopRequested
from media.services import db
from media.worker import Worker, backoff, control_project


def _project(status="QUEUED"):
    pid = db.new_id()
    with db.connect() as conn:
        conn.execute('INSERT INTO "Project" (id, sourceType, folder, status, createdAt, updatedAt) '
                     'VALUES (?,?,?,?,?,?)', [pid, "youtube", "x", status, db.now_iso(), db.now_iso()])
    return pid


def _worker(handlers):
    w = Worker()
    w.handlers = handlers
    return w


def _run_all(w, limit=10):
    for _ in range(limit):
        job = w._next_job()
        if job is None:
            return
        w._execute(job)


def test_phases_chain_download_transcribe_analyze(temp_db):
    calls = []
    w = _worker({k: (lambda t, p, k=k: calls.append(k)) for k in ("download", "transcribe", "analyze")})
    pid = _project()
    db.enqueue_job("download", pid)
    _run_all(w)
    assert calls == ["download", "transcribe", "analyze"]
    assert all(j["status"] == "DONE" for j in db.list_jobs([pid]))


def test_transient_error_retries_with_backoff_then_fails(temp_db):
    def boom(t, p):
        raise RuntimeError("red caída")
    w = _worker({"download": boom})
    pid = _project()
    jid = db.enqueue_job("download", pid)
    for attempt in range(1, 4):
        job = db.get_job(jid)
        assert job["status"] == "QUEUED"
        with db.connect() as conn:  # adelantar la espera
            conn.execute('UPDATE "Job" SET runAfter = NULL WHERE id = ?', [jid])
        w._execute(db.get_job(jid) if db.claim_job(jid) else job)
    job = db.get_job(jid)
    assert job["status"] == "FAILED" and job["attempts"] == 3
    p = db.get_project(pid)
    assert p["status"] == "FAILED" and "red caída" in p["error"]
    assert backoff(1) == 15 and backoff(2) == 60


def test_permanent_error_not_retried(temp_db):
    def private(t, p):
        raise PermanentError("video privado")
    w = _worker({"download": private})
    pid = _project()
    jid = db.enqueue_job("download", pid)
    _run_all(w)
    assert db.get_job(jid)["status"] == "FAILED" and db.get_job(jid)["attempts"] == 1
    assert db.get_project(pid)["error"] == "video privado"


def test_pause_requeues_without_spending_attempt_and_resume(temp_db):
    pid = _project()

    def pause_midway(t, p):
        db.update_project(t, status="PAUSED")
        raise StopRequested("PAUSED")
    w = _worker({"download": pause_midway})
    jid = db.enqueue_job("download", pid)
    _run_all(w)
    job = db.get_job(jid)
    assert job["status"] == "QUEUED" and job["attempts"] == 0
    assert w._next_job() is None  # proyecto en pausa: no se toma
    control_project(w, pid, "resume")
    assert db.get_project(pid)["status"] == "QUEUED"
    w.handlers = {"download": lambda t, p: None, "transcribe": lambda t, p: None, "analyze": lambda t, p: None}
    _run_all(w)
    assert db.get_job(jid)["status"] == "DONE"


def test_stop_cancels_pending_and_discard_deletes(temp_db, tmp_path):
    pid = _project()
    db.enqueue_job("download", pid)
    w = _worker({})
    assert control_project(w, pid, "stop")["status"] == "STOPPED"
    assert db.list_jobs([pid])[0]["status"] == "CANCELLED"
    assert control_project(w, pid, "discard")["status"] == "DELETED"
    assert db.get_project(pid) is None


def test_rate_limited_reschedules_without_attempt(temp_db):
    pid = _project("READY")
    cid = db.insert_clip(pid, {"rank": 0, "startSec": 0, "endSec": 40, "score": 50, "reason": "r", "hook": "h",
                               "title": "t", "description": "d", "hashtags": "#a"})

    def limited(t, p):
        raise RateLimited("tope diario", retry_at="2999-01-01T00:05:00.000+00:00")
    w = _worker({"publish": limited})
    jid = db.enqueue_job("publish", cid)
    _run_all(w)
    job = db.get_job(jid)
    assert job["status"] == "QUEUED" and job["attempts"] == 0 and job["runAfter"].startswith("2999")
    assert db.get_clip(cid)["publishStatus"] == "SCHEDULED"
    assert json.loads(db.get_clip(cid)["publishInfo"])["retryAt"].startswith("2999")


def test_unknown_action(temp_db):
    pid = _project()
    with pytest.raises(PermanentError):
        control_project(_worker({}), pid, "volar")
