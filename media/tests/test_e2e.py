"""Prueba de punta a punta con un video corto real de YouTube con subtítulos.

    .venv/bin/pytest media/tests -m e2e -s

Recorre la API y la cola reales sobre una BD y carpeta temporales:
descarga → subtítulos → momentos → pulido Whisper → reencuadre → render → QA.
Necesita internet, FFmpeg con libass y Deno. Usa Gemini si hay GEMINI_API_KEY
en el entorno; si no, el respaldo sin IA.
"""
import json
import subprocess
import time

import pytest

from media.services import db

VIDEO = "https://www.youtube.com/watch?v=LtMQDPAnauE"  # 4:45, charla en español con subtítulos del creador
TIMEOUT = 25 * 60


def _wait(pred, timeout, every=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        value = pred()
        if value:
            return value
        time.sleep(every)
    return None


@pytest.mark.e2e
def test_youtube_url_to_rendered_vertical_clip(temp_db, monkeypatch):
    monkeypatch.setenv("MAX_CLIPS", "3")
    monkeypatch.setenv("AUTO_RENDER", "1")
    from media.config import reset_settings, settings
    reset_settings()
    from fastapi.testclient import TestClient

    from media.main import app

    with TestClient(app) as client:
        assert client.get("/health").json()["libass"] is True

        pid = db.new_id()
        with db.connect() as conn:
            conn.execute('INSERT INTO "Project" (id, sourceType, sourceUrl, folder, createdAt, updatedAt) '
                         "VALUES (?,?,?,?,?,?)", [pid, "youtube", VIDEO, f"projects/{pid}/", db.now_iso(), db.now_iso()])
        assert client.post("/jobs", json={"type": "download", "targetId": pid}).status_code == 200

        project = _wait(lambda: (p := db.get_project(pid)) and p["status"] in ("READY", "FAILED") and p, TIMEOUT)
        assert project, "el proyecto no terminó a tiempo"
        assert project["status"] == "READY", project["error"]
        assert project["transcriptSource"] in ("youtube-manual", "youtube-auto")
        assert project["progress"] == 100

        folder = settings().projects_dir / pid
        info = json.loads((folder / "source.info.json").read_text())
        assert info["duration"] > 200
        clips = db.list_clips(pid)
        assert 1 <= len(clips) <= 3
        for c in clips:
            assert 20 <= c["endSec"] - c["startSec"] <= 95
            assert c["title"] and c["hook"] and c["hashtags"].startswith("#")
            caps = json.loads((folder / "clips" / c["id"] / "captions.json").read_text())
            assert len(caps["words"]) > 20

        first = clips[0]["id"]
        done = _wait(lambda: (c := db.get_clip(first)) and c["renderStatus"] in ("DONE", "FAILED") and c, TIMEOUT)
        assert done and done["renderStatus"] == "DONE", done and done["renderError"]

        final = settings().data_dir / done["outputPath"]
        probe = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,avg_frame_rate:format=duration",
             "-of", "json", str(final)], capture_output=True, text=True).stdout)
        v = next(s for s in probe["streams"] if s["codec_name"] == "h264")
        assert (v["width"], v["height"], v["avg_frame_rate"]) == (1080, 1920, "30/1")
        assert any(s["codec_name"] == "aac" for s in probe["streams"])
        expected = done["endSec"] - done["startSec"]
        assert abs(float(probe["format"]["duration"]) - expected) < 1.5
        assert (final.parent / "clip.ass").exists() and (final.parent / "reframed.mp4.layout.json").exists()
        assert (final.parent / "thumb.jpg").exists()

        # Archivos servidos con Range (el <video> los pide así) y descarga con nombre.
        rel = done["outputPath"].removeprefix("projects/")
        r = client.get(f"/files/projects/{rel}", headers={"Range": "bytes=0-99"})
        assert r.status_code == 206 and len(r.content) == 100
        d = client.get(f"/download/clip/{first}")
        assert d.status_code == 200 and "attachment" in d.headers["content-disposition"]

        # Limpiar borra la fuente pero los clips siguen disponibles.
        assert _wait(lambda: all(c["renderStatus"] in ("DONE", "FAILED") for c in db.list_clips(pid)), TIMEOUT)
        assert client.post(f"/projects/{pid}/cleanup").status_code == 200
        assert not (folder / "source.mp4").exists() and final.exists()
