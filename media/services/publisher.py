"""Publicación (plan 4 y 6.7): interfaz común con un proveedor por ruta.

    publish(clip, title, description, hashtags, when, provider=...) -> PublishResult

* `manual` — kit de publicación (MP4 + título + descripción + hashtags). Siempre
  disponible; no sale nada a internet.
* `upload_post` — intermediario Upload-Post (API pública, `Authorization: Apikey`).
  El plan gratis permite ~10 subidas al mes y no incluye TikTok. Un 429 lanza
  `RateLimited` y la cola lo reprograma para el día siguiente.
* `tiktok_draft` — envío a borradores de TikTok con tu propia app
  (Content Posting API, `video.upload`, subida FILE_UPLOAD). Terminas de editar
  y publicas desde la notificación en la app de TikTok. Máximo 5 pendientes/24 h.

Escrito desde cero: los publicadores de OpenShorts/ClipPyMe no se reutilizan.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import httpx

from media.config import settings
from media.errors import RateLimited, next_day_iso  # noqa: F401  (reexportados)

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_INBOX_INIT = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_STATUS = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
UPLOAD_POST_URL = "https://api.upload-post.com/api/upload"

MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024


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
                                       ("description", caption_text("", description, hashtags))]
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


# ── TikTok (borradores) ──────────────────────────────────────────────────────

def _secrets_dir() -> Path:
    d = settings().data_dir / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _fernet():
    from cryptography.fernet import Fernet
    key_path = _secrets_dir() / "token.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        os.chmod(key_path, 0o600)
    return Fernet(key_path.read_bytes())


def save_token(data: dict) -> None:
    path = _secrets_dir() / "tiktok_token.enc"
    path.write_bytes(_fernet().encrypt(json.dumps(data).encode()))
    os.chmod(path, 0o600)


def load_token() -> dict | None:
    path = _secrets_dir() / "tiktok_token.enc"
    if not path.exists():
        return None
    try:
        return json.loads(_fernet().decrypt(path.read_bytes()))
    except Exception:
        return None


_oauth_states: dict[str, float] = {}


def tiktok_auth_url() -> str:
    s = settings()
    if not (s.tiktok_client_key and s.tiktok_client_secret):
        raise PublishError("Falta TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET en .env")
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time()
    return TIKTOK_AUTH_URL + "?" + urlencode({
        "client_key": s.tiktok_client_key, "scope": "video.upload", "response_type": "code",
        "redirect_uri": s.tiktok_redirect_uri, "state": state})


def tiktok_exchange_code(code: str, state: str) -> dict:
    issued = _oauth_states.pop(state, None)
    if issued is None or time.time() - issued > 900:
        raise PublishError("Estado OAuth inválido o caducado; vuelve a conectar TikTok.")
    return _token_request({"code": code, "grant_type": "authorization_code",
                           "redirect_uri": settings().tiktok_redirect_uri})


def _token_request(fields: dict) -> dict:
    s = settings()
    r = httpx.post(TIKTOK_TOKEN_URL, data={"client_key": s.tiktok_client_key,
                                           "client_secret": s.tiktok_client_secret, **fields},
                   headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    body = r.json() if r.content else {}
    if r.status_code >= 400 or "access_token" not in body:
        raise PublishError(f"TikTok OAuth: {body.get('error_description') or body.get('error') or r.text[:200]}")
    body["obtained_at"] = time.time()
    save_token(body)
    return {"open_id": body.get("open_id"), "scope": body.get("scope")}


def _tiktok_access_token() -> str:
    tok = load_token()
    if not tok:
        raise PublishError("TikTok no está conectado. Conéctalo desde la app (botón «Conectar TikTok»).")
    if time.time() > tok.get("obtained_at", 0) + int(tok.get("expires_in", 0)) - 120:
        _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        tok = load_token() or {}
    return tok["access_token"]


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) según las reglas de TikTok: < 5 MB en un
    solo trozo; trozos de 5–64 MB; el último puede ser mayor (hasta 128 MB)."""
    if size <= MAX_CHUNK:
        return size, 1
    chunk = 10 * 1024 * 1024
    return chunk, max(1, size // chunk)


class TikTokDraft:
    name = "tiktok_draft"
    label = "Borrador de TikTok"

    def available(self) -> bool:
        s = settings()
        return bool(s.tiktok_client_key and s.tiktok_client_secret)

    def connected(self) -> bool:
        return load_token() is not None

    def publish(self, video: Path, title: str, description: str, hashtags: str, when=None, **_) -> PublishResult:
        token = _tiktok_access_token()
        size = video.stat().st_size
        chunk, count = chunk_plan(size)
        r = httpx.post(TIKTOK_INBOX_INIT, headers={"Authorization": f"Bearer {token}",
                                                   "Content-Type": "application/json; charset=UTF-8"},
                       json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                             "chunk_size": chunk, "total_chunk_count": count}}, timeout=60)
        body = r.json() if r.content else {}
        err = (body.get("error") or {}).get("code", "")
        if err == "spam_risk_too_many_pending_share" or r.status_code == 429:
            raise RateLimited("TikTok: tope de 5 borradores pendientes en 24 h")
        if r.status_code >= 400 or err not in ("", "ok"):
            raise PublishError(f"TikTok init: {body.get('error') or r.text[:300]}")
        data = body["data"]
        with open(video, "rb") as fh:
            for i in range(count):
                start = i * chunk
                length = size - start if i == count - 1 else chunk
                fh.seek(start)
                piece = fh.read(length)
                up = httpx.put(data["upload_url"], content=piece, timeout=600, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(piece)),
                    "Content-Range": f"bytes {start}-{start + len(piece) - 1}/{size}"})
                if up.status_code >= 400:
                    raise PublishError(f"TikTok subida: {up.status_code} {up.text[:200]}")
        return PublishResult(self.name, "DRAFT", info={
            "publish_id": data.get("publish_id"),
            "caption": caption_text(title, description, hashtags),
            "note": "Abre la notificación en la app de TikTok para terminar de editar y publicar."})


PROVIDERS = {p.name: p for p in (ManualKit(), UploadPost(), TikTokDraft())}


def providers_status() -> list[dict]:
    out = []
    for p in PROVIDERS.values():
        item = {"name": p.name, "label": p.label, "available": p.available()}
        if isinstance(p, TikTokDraft):
            item["connected"] = p.connected()
        out.append(item)
    return out


def publish(clip: dict, title: str, description: str, hashtags: str, when: str | None = None, *,
            provider: str = "manual", video: Path | None = None, **kwargs) -> PublishResult:
    """Interfaz común del plan 6.7."""
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


__all__ = ["publish", "providers_status", "RateLimited", "PublishError", "PublishResult", "chunk_plan",
           "tiktok_auth_url", "tiktok_exchange_code"]
