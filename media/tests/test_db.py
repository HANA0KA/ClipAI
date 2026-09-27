from media.services import db


def test_ids_are_cuid_like():
    ids = {db.new_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(i.isalnum() and i.islower() and 20 <= len(i) <= 30 for i in ids)


def test_project_clip_job_roundtrip(temp_db):
    pid = db.new_id()
    with db.connect() as conn:
        conn.execute('INSERT INTO "Project" (id, sourceType, folder, createdAt, updatedAt) VALUES (?,?,?,?,?)',
                     [pid, "youtube", "x", db.now_iso(), db.now_iso()])
    db.update_project(pid, status="DOWNLOADING", progress=5, sourceDeleted=True)
    p = db.get_project(pid)
    assert p["status"] == "DOWNLOADING" and p["progress"] == 5 and p["sourceDeleted"] == 1
    assert p["updatedAt"].endswith("+00:00")

    cid = db.insert_clip(pid, {"rank": 0, "startSec": 1.0, "endSec": 40.0, "score": 80, "reason": "r",
                               "hook": "h", "title": "t #Shorts", "description": "d", "hashtags": "#a",
                               "signals": {"heat": 0.5}})
    assert db.get_clip(cid)["signals"] == '{"heat": 0.5}'
    assert [c["id"] for c in db.list_clips(pid)] == [cid]

    jid = db.enqueue_job("download", pid)
    assert [j["id"] for j in db.queued_jobs()] == [jid]
    assert db.claim_job(jid) is True
    assert db.claim_job(jid) is False  # ya está RUNNING
    db.fail_job(jid, "boom", retry_in=60)
    assert db.get_job(jid)["status"] == "QUEUED"
    assert db.queued_jobs() == []  # espera pendiente
    assert db.requeue_running_jobs() == 0

    db.delete_project(pid)
    assert db.get_clip(cid) is None  # onDelete: Cascade
