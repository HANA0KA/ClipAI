"""Tarea `publish` (Upload-Post)."""
from __future__ import annotations

import json

from media.errors import PermanentError
from media.config import settings
from media.services import db, hashtags, publish_text
from media.services.publisher import PublishError, publish
from media.tasks.common import log, project_folder


def _clip(clip_id: str) -> dict:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise PermanentError("El clip ya no existe.")
    if clip.get("renderStatus") != "DONE" or not clip.get("outputPath"):
        raise PermanentError("Renderiza el clip antes de publicarlo.")
    return clip


def post_text(clip: dict, hook: str | None = None, hashtags_line: str | None = None) -> dict:
    """Título, descripción y hashtags para publicar (con el creador del video original)."""
    project = db.get_project(clip["projectId"]) or {}
    uploaded = project.get("sourceType") == "upload"
    return publish_text.build(
        hook if hook is not None else (clip.get("hook") or clip.get("title") or ""),
        hashtags_line if hashtags_line is not None else (clip.get("hashtags") or ""),
        creator=publish_text.creator_for(project_folder(clip["projectId"])), video_title=project.get("title"),
        source_url=None if uploaded else project.get("sourceUrl"), fmt=settings().hashtags_format)


def network_hashtags(clip: dict, platform: str) -> str:
    """Hashtags de YouTube o Instagram para este clip: sus fijas de todos los videos + las sugeridas del clip."""
    try:
        sets = json.loads(clip.get("hashtagSets") or "{}") or {}
    except ValueError:
        sets = {}
    pins = publish_text.network_pins(settings().data_dir / "network-hashtags.json")
    return " ".join(hashtags.compose_network(platform, sets.get(platform) or [], pins.get(platform) or []))


def _run(clip_id: str, provider: str, payload: dict) -> None:
    clip = _clip(clip_id)
    db.update_clip(clip_id, publishStatus="RUNNING")
    try:
        # El gancho (con su emoji) sigue siendo el de la portada; al publicar se le suma el creador.
        text = post_text(clip)
        tags = text["hashtags"]
        # YouTube/Instagram: las tuyas para todos los videos + las del clip
        net = (payload.get("platforms") or ["youtube"])[0]
        if net in hashtags.NETWORK_CAPS:
            tags = network_hashtags(clip, net) or tags
        result = publish(clip, text["title"], text["description"], tags,
                         payload.get("when"), provider=provider, platforms=payload.get("platforms"))
    except PublishError as exc:
        raise PermanentError(str(exc)) from exc
    fields = {"publishStatus": result.status,
              "publishInfo": json.dumps({"provider": result.provider, "url": result.url, **result.info},
                                        ensure_ascii=False)}
    if result.status == "DONE":
        from media.services.db import now_iso
        fields["postedAt"] = now_iso()
    db.update_clip(clip_id, **fields)
    log.info("publicado %s vía %s: %s", clip_id, provider, result.status)


def run_publish(clip_id: str, payload: dict) -> None:
    _run(clip_id, payload.get("provider") or "upload_post", payload)
