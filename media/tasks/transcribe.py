"""Tarea `transcribe`: subtítulos de YouTube primero, Whisper de respaldo.

Orden: subtítulos manuales → automáticos (json3, VTT de respaldo) →
youtube-transcript-api → Whisper completo (archivos subidos o sin subtítulos).
Nunca traducciones automáticas. Salida: transcript.json con palabras y frases.
"""
from __future__ import annotations

from pathlib import Path

from media.services import db, source_cache, transcript, whisper
from media.services.atomic import read_json, write_json
from media.tasks.common import check_stop, log, progress, project_folder, require_project

MIN_WORDS = 30  # menos que esto no alcanza para elegir momentos


def _from_transcript_api(video_id: str, lang: str) -> list[dict]:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    listing = api.list(video_id)
    wanted = [lang] if lang else []
    wanted += [x for x in ("es", "en") if x not in wanted]
    chosen = None
    try:
        chosen = listing.find_manually_created_transcript(wanted)
    except Exception:
        try:
            chosen = listing.find_generated_transcript(wanted)
        except Exception:
            chosen = next(iter(listing), None)  # el idioma original, sea cual sea
    if chosen is None:
        return []
    fetched = chosen.fetch()
    return transcript.words_from_snippets([{"text": s.text, "start": s.start, "duration": s.duration}
                                           for s in fetched])


def run_task(project_id: str, payload: dict) -> None:
    project = require_project(project_id)
    folder = project_folder(project_id)
    out = folder / "transcript.json"
    key = source_cache.project_key(project, folder)
    cached = source_cache.load(key, "transcript.json")
    if out.exists() and (read_json(out, {}) or {}).get("words"):
        log.info("transcripción ya hecha (punto de control)")
        data = read_json(out, {})
    elif cached and len(cached.get("words") or []) >= MIN_WORDS:
        log.info("transcripción reutilizada de la caché (%s)", key)
        progress(project_id, 50, status="TRANSCRIBING", stage="Reutilizando la transcripción de este video")
        data = cached
        write_json(out, data)
    else:
        progress(project_id, 21, status="TRANSCRIBING", stage="Buscando subtítulos")
        info = read_json(folder / "source.info.json", {}) or {}
        words, source, lang = [], None, (project.get("language") or "").split("-")[0]

        if project["sourceType"] == "youtube":
            track, kind, lang = transcript.pick_track(folder, info)
            if track is not None:
                try:
                    words = transcript.parse_subtitle_file(track)
                    source = f"youtube-{kind}"
                except Exception as exc:
                    log.warning("no se pudo leer %s: %s", track.name, exc)
            if len(words) < MIN_WORDS and info.get("id"):
                progress(project_id, 25, stage="Probando youtube-transcript-api")
                try:
                    words = _from_transcript_api(info["id"], lang)
                    source = "transcript-api"
                except Exception as exc:
                    log.warning("youtube-transcript-api falló: %s", str(exc)[:200])
                    words = []

        if len(words) < MIN_WORDS:
            check_stop(project_id)
            progress(project_id, 26, stage="Transcribiendo con Whisper (puede tardar)")
            last = {"v": -1}

            def on_progress(frac: float) -> None:
                v = 26 + 32 * frac
                if int(v) != last["v"]:
                    last["v"] = int(v)
                    progress(project_id, v)

            words, lang = whisper.transcribe(folder / "audio.wav", language=lang or None, progress=on_progress)
            source = "whisper"

        if len(words) < MIN_WORDS:
            from media.errors import PermanentError
            raise PermanentError("El video casi no tiene habla: no hay texto suficiente para elegir momentos.")
        data = {"source": source, "language": lang or "es", "words": words,
                "sentences": transcript.to_sentences(words)}
        write_json(out, data)
        source_cache.save(key, "transcript.json", data)

    db.update_project(project_id, transcriptSource=data.get("source"), language=data.get("language"),
                      progress=60, stage=f"Transcripción lista ({len(data['words'])} palabras)")


def load(folder: Path) -> dict:
    return read_json(folder / "transcript.json", {}) or {}
