"""Tareas `publish` (Upload-Post) y `tiktok_draft` (borrador de TikTok)."""
from __future__ import annotations

import json

from media.errors import PermanentError
from media.services import db
from media.services.publisher import PublishError, publish
from media.tasks.common import log


def _clip(clip_id: str) -> dict:
    clip = db.get_clip(clip_id)
    if clip is None:
        raise PermanentError("El clip ya no existe.")
    if clip.get("renderStatus") != "DONE" or not clip.get("outputPath"):
        raise PermanentError("Renderiza el clip antes de publicarlo.")
    return clip


def _run(clip_id: str, provider: str, payload: dict) -> None:
    clip = _clip(clip_id)
    db.update_clip(clip_id, publishStatus="RUNNING")
    try:
        result = publish(clip, clip["title"], clip["description"], clip["hashtags"], payload.get("when"),
                         provider=provider, platforms=payload.get("platforms"))
    except PublishError as exc:
        raise PermanentError(str(exc)) from exc
    fields = {"publishStatus": result.status,
              "publishInfo": json.dumps({"provider": result.provider, "url": result.url, **result.info},
                                        ensure_ascii=False)}
    if provider == "tiktok_draft":
        fields["tiktokDraft"] = True
    elif result.status == "DONE":
        from media.services.db import now_iso
        fields["postedAt"] = now_iso()
    db.update_clip(clip_id, **fields)
    log.info("publicado %s vía %s: %s", clip_id, provider, result.status)


def run_publish(clip_id: str, payload: dict) -> None:
    _run(clip_id, payload.get("provider") or "upload_post", payload)


def run_tiktok_draft(clip_id: str, payload: dict) -> None:
    _run(clip_id, "tiktok_draft", payload)
