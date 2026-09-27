"""Configuración del servicio media, leída del `.env` de la raíz.

Todas las variables están documentadas en `.env.example`. `settings()` se
cachea; los tests llaman a `reset_settings()` tras cambiar el entorno.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = ROOT_DIR / "media"
FONTS_DIR = MEDIA_DIR / "fonts"
TEMPLATES_DIR = MEDIA_DIR / "templates"

load_dotenv(ROOT_DIR / ".env", override=False)


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name) or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = _str(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "si", "sí")


def _path(raw: str) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (ROOT_DIR / p).resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    media_host: str
    media_port: int
    # IA
    gemini_api_key: str
    vertex_project_id: str
    vertex_location: str
    google_service_account_json: str
    google_service_account_file: str
    gemini_model: str
    gemini_fallback_models: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    embeddings_enabled: bool
    embeddings_model: str
    # Transcripción
    whisper_engine: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    polish_with_whisper: bool
    hf_token: str
    # Selección
    max_clips: int
    clip_min_sec: float
    clip_max_sec: float
    prefilter_top: int
    auto_render: bool
    max_video_minutes: int
    min_free_disk_gb: float
    # Render
    ffmpeg_bin: str
    ffprobe_bin: str
    video_encoder: str
    x264_crf: int
    x264_preset: str
    target_lufs: float
    ken_burns_zoom: float
    # Descarga
    ytdlp_cookies_from_browser: str
    # Publicación
    upload_post_api_key: str
    upload_post_user: str
    tiktok_client_key: str
    tiktok_client_secret: str
    tiktok_redirect_uri: str

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def vertex_configured(self) -> bool:
        return bool(self.vertex_project_id and (self.google_service_account_json
                                                or self.google_service_account_file))

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model) or self.vertex_configured or bool(self.gemini_api_key)


def _db_path(data_dir: Path) -> Path:
    raw = _str("DATABASE_URL")
    if raw.startswith("file:"):
        return _path(raw[len("file:"):])
    return data_dir / "app.db"


@lru_cache(maxsize=1)
def settings() -> Settings:
    data_dir = _path(_str("DATA_DIR", "./data"))
    return Settings(
        data_dir=data_dir,
        db_path=_db_path(data_dir),
        media_host=_str("MEDIA_HOST", "127.0.0.1"),
        media_port=_int("MEDIA_PORT", 8000),
        gemini_api_key=_str("GEMINI_API_KEY"),
        vertex_project_id=_str("VERTEX_PROJECT_ID"),
        vertex_location=_str("VERTEX_LOCATION", "us-central1"),
        google_service_account_json=_str("GOOGLE_SERVICE_ACCOUNT_JSON"),
        google_service_account_file=str(_path(_str("GOOGLE_SERVICE_ACCOUNT_FILE"))) if _str("GOOGLE_SERVICE_ACCOUNT_FILE") else "",
        gemini_model=_str("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_fallback_models=_str("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.6-flash,gemini-flash-latest,gemini-3.5-flash-lite,gemini-2.5-flash-lite"),
        llm_base_url=_str("LLM_BASE_URL").rstrip("/"),
        llm_model=_str("LLM_MODEL"),
        llm_api_key=_str("LLM_API_KEY"),
        embeddings_enabled=_bool("EMBEDDINGS_ENABLED", True),
        embeddings_model=_str("EMBEDDINGS_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"),
        whisper_engine=_str("WHISPER_ENGINE", "faster-whisper").lower(),
        whisper_model=_str("WHISPER_MODEL", "small"),
        whisper_device=_str("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=_str("WHISPER_COMPUTE_TYPE", "int8"),
        polish_with_whisper=_bool("POLISH_WITH_WHISPER", True),
        hf_token=_str("HF_TOKEN"),
        max_clips=max(1, _int("MAX_CLIPS", 8)),
        clip_min_sec=_float("CLIP_MIN_SEC", 30.0),
        clip_max_sec=_float("CLIP_MAX_SEC", 90.0),
        prefilter_top=max(1, _int("PREFILTER_TOP", 30)),
        auto_render=_bool("AUTO_RENDER", True),
        max_video_minutes=_int("MAX_VIDEO_MINUTES", 240),
        min_free_disk_gb=_float("MIN_FREE_DISK_GB", 3.0),
        ffmpeg_bin=_str("FFMPEG_BIN"),
        ffprobe_bin=_str("FFPROBE_BIN"),
        video_encoder=_str("VIDEO_ENCODER", "libx264"),
        x264_crf=min(51, max(0, _int("X264_CRF", 18))),
        x264_preset=_str("X264_PRESET", "medium"),
        target_lufs=_float("TARGET_LUFS", -14.0),
        ken_burns_zoom=_float("KEN_BURNS_ZOOM", 1.05),
        ytdlp_cookies_from_browser=_str("YTDLP_COOKIES_FROM_BROWSER"),
        upload_post_api_key=_str("UPLOAD_POST_API_KEY"),
        upload_post_user=_str("UPLOAD_POST_USER"),
        tiktok_client_key=_str("TIKTOK_CLIENT_KEY"),
        tiktok_client_secret=_str("TIKTOK_CLIENT_SECRET"),
        tiktok_redirect_uri=_str("TIKTOK_REDIRECT_URI", "http://127.0.0.1:3000/api/tiktok/callback"),
    )


def reset_settings() -> None:
    settings.cache_clear()
