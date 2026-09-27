"""Publicación: interfaz común, troceo de TikTok, límites y kit manual."""
from datetime import datetime, timezone

import httpx
import pytest

from media.errors import RateLimited, next_day_iso
from media.services import publisher

MB = 1024 * 1024


def test_chunk_plan_follows_tiktok_rules():
    assert publisher.chunk_plan(3 * MB) == (3 * MB, 1)          # < 5 MB: entero
    assert publisher.chunk_plan(40 * MB) == (40 * MB, 1)        # ≤ 64 MB: un trozo
    chunk, count = publisher.chunk_plan(150 * MB)                # > 64 MB: varios
    assert 5 * MB <= chunk <= 64 * MB and count == 15
    last = 150 * MB - chunk * (count - 1)
    assert chunk <= last <= 128 * MB


def test_next_day_is_utc_and_in_future():
    iso = next_day_iso()
    assert iso.endswith("+00:00")
    assert datetime.fromisoformat(iso) > datetime.now(timezone.utc)
    assert RateLimited("x").retry_at.endswith("+00:00")


def test_manual_kit_and_unconfigured_provider(temp_db, tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"0" * 20000)
    r = publisher.publish({}, "Título #Shorts", "Desc", "#a #b", provider="manual", video=video)
    assert r.status == "KIT" and r.info["hashtags"] == "#a #b"
    with pytest.raises(publisher.PublishError):
        publisher.publish({}, "t", "d", "#a", provider="upload_post", video=video)
    names = {p["name"]: p for p in publisher.providers_status()}
    assert names["manual"]["available"] and not names["upload_post"]["available"]


def test_upload_post_429_raises_rate_limited(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "k")
    monkeypatch.setenv("UPLOAD_POST_USER", "yo")
    from media.config import reset_settings
    reset_settings()
    video = tmp_path / "final.mp4"
    video.write_bytes(b"0" * 20000)
    sent = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        sent.update(url=url, headers=headers, data=data)
        return httpx.Response(429, json={"usage": {"count": 10, "limit": 10}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(publisher.httpx, "post", fake_post)
    with pytest.raises(RateLimited):
        publisher.publish({}, "Título", "Desc", "#a", provider="upload_post", video=video)
    assert sent["headers"]["Authorization"] == "Apikey k"
    assert ("platform[]", "youtube") in sent["data"] and ("user", "yo") in sent["data"]
