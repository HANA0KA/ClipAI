"""Publicación: interfaz común con un proveedor por ruta.

    publish(clip, title, description, hashtags, when, provider=...) -> PublishResult

* `manual` — kit de publicación (MP4 + título + descripción + hashtags). Siempre
  disponible; no sale nada a internet.
* `upload_post` — intermediario Upload-Post (API pública, `Authorization: Apikey`).
  El plan gratis permite ~10 subidas al mes. Un 429 lanza
  `RateLimited` y la cola lo reprograma para el día siguiente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from media.config import settings
from media.errors import RateLimited, next_day_iso  # noqa: F401  (reexportados)

UPLOAD_POST_URL = "https://api.upload-post.com/api/upload"


class PublishError(RuntimeError):
    pass


@dataclass
class PublishResult:
    provider: str
    status: str  # DONE | DRAFT | KIT
    url: str | None = None
    info: dict = field(default_factory=dict)


def caption_text(title: str, description: str, hashtags: str) -> str:
    return "\n\n".join(p for p in (title.strip(), description.strip(), hashtags.strip()) if p)


# ── Kit manual ───────────────────────────────────────────────────────────────

class ManualKit:
    name = "manual"
    label = "Kit de publicación (subida manual)"

    def available(self) -> bool:
        return True

    def publish(self, video: Path, title: str, description: str, hashtags: str, when=None, **_) -> PublishResult:
        return PublishResult(self.name, "KIT", info={
            "video": str(video), "title": title, "description": description, "hashtags": hashtags,
            "steps": ["Descarga el MP4", "Súbelo desde la app de YouTube o TikTok (o YouTube Studio)",
                      "Pega el título, la descripción y los hashtags"]})


# ── Upload-Post ──────────────────────────────────────────────────────────────

class UploadPost:
    name = "upload_post"
    label = "Upload-Post (intermediario)"

    def available(self) -> bool:
        s = settings()
        return bool(s.upload_post_api_key and s.upload_post_user)

    def publish(self, video: Path, title: str, description: str, hashtags: str, when=None,
                platforms: list[str] | None = None, **_) -> PublishResult:
        s = settings()
        if not self.available():
            raise PublishError("Falta UPLOAD_POST_API_KEY / UPLOAD_POST_USER en .env")
        platforms = platforms or ["youtube"]
        data: list[tuple[str, str]] = [("user", s.upload_post_user), ("title", title[:100]),
                                       ("description", caption_text("", description or title, hashtags))]  # el gancho es título y descripción
        data += [("platform[]", p) for p in platforms]
        if "youtube" in platforms:
            data += [("privacyStatus", "public")]
        if when:
            data.append(("scheduled_date", when))
        with open(video, "rb") as fh:
            r = httpx.post(UPLOAD_POST_URL, headers={"Authorization": f"Apikey {s.upload_post_api_key}"},
                           data=data, files={"video": (video.name, fh, "video/mp4")}, timeout=600)
        if r.status_code == 429:
            raise RateLimited(f"Upload-Post: límite alcanzado ({r.text[:200]})")
        if r.status_code >= 400:
            raise PublishError(f"Upload-Post respondió {r.status_code}: {r.text[:300]}")
        body = r.json()
        results = body.get("results") or {}
        urls = {k: v.get("url") for k, v in results.items() if isinstance(v, dict)}
        failed = {k: v for k, v in results.items() if isinstance(v, dict) and not v.get("success", True)}
        if failed:
            raise PublishError(f"Upload-Post: falló en {', '.join(failed)}: {json.dumps(failed)[:300]}")
        return PublishResult(self.name, "DONE", next(iter(urls.values()), None),
                             {"urls": urls, "usage": body.get("usage")})


PROVIDERS = {p.name: p for p in (ManualKit(), UploadPost())}


def providers_status() -> list[dict]:
    out = []
    for p in PROVIDERS.values():
        out.append({"name": p.name, "label": p.label, "available": p.available()})
    return out


def publish(clip: dict, title: str, description: str, hashtags: str, when: str | None = None, *,
            provider: str = "manual", video: Path | None = None, **kwargs) -> PublishResult:
    """Interfaz común de publicación."""
    impl = PROVIDERS.get(provider)
    if impl is None:
        raise PublishError(f"Proveedor desconocido: {provider}")
    if not impl.available():
        raise PublishError(f"El proveedor {impl.label} no está configurado en .env")
    if video is None:
        video = settings().data_dir / (clip.get("outputPath") or "")
    if not video.exists():
        raise PublishError("El clip aún no está renderizado.")
    return impl.publish(video, title, description, hashtags, when=when, **kwargs)


__all__ = ["publish", "providers_status", "RateLimited", "PublishError", "PublishResult"]
