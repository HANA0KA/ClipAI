"""Fuentes de video (YouTube y Kick): reconocer enlaces, tramos, fichas recortadas y descarga por tramo."""
import pytest

from media.services import sources
from media.services.sources import SourceError

UUID = "01a0e420-01d0-77c8-8e8f-b8e88cdff2d4"


def test_parse_kick_vod_channel_clip_and_unknown():
    for url in (f"https://kick.com/westcol/videos/{UUID}", f"kick.com/westcol/videos/{UUID.upper()}?x=1",
                f"https://www.kick.com/video/{UUID}"):
        got = sources.parse(url)
        assert got["type"] == "kick" and got["kind"] == "video" and got["id"] == UUID
    assert sources.parse(f"https://kick.com/westcol/videos/{UUID}")["channel"] == "westcol"
    ch = sources.parse("https://kick.com/westcol")
    assert ch == {"type": "kick", "kind": "channel", "id": "westcol", "channel": "westcol"}
    assert sources.parse("https://kick.com/westcol/videos")["kind"] == "channel"
    assert sources.parse("https://kick.com/westcol?clip=clip_01ABC")["kind"] == "clip"
    assert sources.parse("https://kick.com/westcol/clips/clip_01ABC")["kind"] == "clip"
    for bad in ("https://kick.com/", "https://kick.com/categories/just-chatting", "https://kick.com/westcol/videos/no-es-uuid",
                "https://notkick.com/westcol/videos/" + UUID, "https://vimeo.com/123", "", None, "solo texto"):
        got = sources.parse(bad)
        assert got is None or got["kind"] != "video", bad


def test_parse_youtube_still_works():
    got = sources.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5")
    assert got == {"type": "youtube", "kind": "video", "id": "dQw4w9WgXcQ", "channel": None}
    assert sources.parse("https://youtu.be/dQw4w9WgXcQ")["type"] == "youtube"
    assert sources.parse("https://www.youtube.com/playlist?list=PL123") is None


def test_parse_youtube_channels_in_all_their_forms():
    uc = "UCECJDeK0MNapZbpaOzxrUPA"
    cases = {
        "https://www.youtube.com/@LuisitoComunica": "@LuisitoComunica",
        "youtube.com/@LuisitoComunica/videos": "@LuisitoComunica",
        "https://m.youtube.com/@Westcol_Oficial/streams?x=1": "@Westcol_Oficial",
        f"https://youtube.com/channel/{uc}/videos": f"channel/{uc}",
        "https://www.youtube.com/c/LuisitoComunica": "c/LuisitoComunica",
        "https://www.youtube.com/user/abc": "user/abc",
    }
    for url, key in cases.items():
        assert sources.parse(url) == {"type": "youtube", "kind": "channel", "id": key, "channel": key}, url
    for bad in ("https://www.youtube.com/", "https://www.youtube.com/@a", "https://www.youtube.com/channel/UCcorto",
                "https://www.youtube.com/playlist?list=PL123", "https://www.youtube.com/results?search_query=x",
                "https://notyoutube.com/@LuisitoComunica", "@LuisitoComunica"):
        assert sources.parse(bad) is None, bad
    # un video sigue siendo un video aunque el enlace traiga el canal
    assert sources.parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ&ab_channel=X")["kind"] == "video"
    assert sources.parse("https://www.youtube.com/live/dQw4w9WgXcQ")["kind"] == "video"
    assert sources.key(sources.parse("https://www.youtube.com/@LuisitoComunica")) is None  # no es una fuente de proyecto


def test_youtube_channel_key_accepts_bare_handles_only_when_asked():
    uc = "UCECJDeK0MNapZbpaOzxrUPA"
    assert sources.youtube_channel_key("@Luisito", allow_bare=True) == "@Luisito"
    assert sources.youtube_channel_key("Luisito.Comunica", allow_bare=True) == "@Luisito.Comunica"
    assert sources.youtube_channel_key(uc, allow_bare=True) == f"channel/{uc}"
    assert sources.youtube_channel_key("@Luisito") is None
    for bad in ("ab", "@ab", "", None, "https://kick.com/westcol", "con espacios"):
        assert sources.youtube_channel_key(bad, allow_bare=True) is None, bad


class _FakeYDL:
    """yt_dlp.YoutubeDL de mentira: devuelve la ficha plana de un canal (o falla como yt-dlp)."""
    calls: list[str] = []
    plan: dict = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        import yt_dlp
        _FakeYDL.calls.append(url)
        got = _FakeYDL.plan[url]
        if isinstance(got, str):
            raise yt_dlp.utils.DownloadError(got)
        return got


def _channel_info(entries):
    return {"channel": "Luisito Comunica", "uploader_id": "@luisitocomunica", "channel_follower_count": 46_000_000,
            "channel_is_verified": True,
            "thumbnails": [{"url": "https://x/banner.jpg", "width": 2560, "height": 424}, {"url": "https://x/avatar.jpg", "width": 900, "height": 900}],
            "entries": entries}


def test_youtube_channel_videos_lists_flat_entries(monkeypatch):
    import yt_dlp
    sources._yt_cache.clear()
    _FakeYDL.calls = []
    _FakeYDL.plan = {"https://www.youtube.com/@Luisito/videos": _channel_info([
        {"id": "dQw4w9WgXcQ", "title": "Corto", "duration": 1200, "view_count": 5000},
        {"id": "aaaaaaaaaaa", "title": "Larguísimo", "duration": 5 * 3600, "view_count": None},
        {"id": "bbbbbbbbbbb", "title": "En vivo", "duration": None, "live_status": "is_live"},
        {"id": "solo-corto", "title": "Id inválido", "duration": 10},
        {"id": "ccccccccccc", "title": "Miembros", "duration": 60, "availability": "subscriber_only"},
    ])}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    got = sources.youtube_channel_videos("@Luisito", "videos", max_minutes=120)
    assert got["profile"] == {"name": "Luisito Comunica", "avatar": "https://x/avatar.jpg", "followers": 46_000_000,
                              "verified": True, "handle": "@luisitocomunica"}
    by_id = {v["id"]: v for v in got["videos"]}
    assert list(by_id) == ["dQw4w9WgXcQ", "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]  # el id inválido se descarta
    assert by_id["dQw4w9WgXcQ"]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert by_id["dQw4w9WgXcQ"]["tooLong"] is False and by_id["aaaaaaaaaaa"]["tooLong"] is True
    assert by_id["bbbbbbbbbbb"]["live"] is True and by_id["ccccccccccc"]["membersOnly"] is True
    assert by_id["dQw4w9WgXcQ"]["thumbnail"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
    # la segunda consulta sale de la caché (no vuelve a llamar a yt-dlp)
    sources.youtube_channel_videos("@luisito", "videos", max_minutes=120)
    assert _FakeYDL.calls == ["https://www.youtube.com/@Luisito/videos"]


def test_youtube_channel_videos_handles_missing_tab_and_missing_channel(monkeypatch):
    import yt_dlp
    sources._yt_cache.clear()
    _FakeYDL.calls = []
    _FakeYDL.plan = {
        "https://www.youtube.com/@Ibai/streams": "ERROR: [youtube:tab] @Ibai: This channel does not have a streams tab",
        "https://www.youtube.com/@Ibai/videos": _channel_info([]),
        "https://www.youtube.com/@Nadie/videos": "ERROR: [youtube:tab] @Nadie/videos: Unable to download API page: HTTP Error 404: Not Found",
        "https://www.youtube.com/@Roto/videos": "ERROR: [youtube] algo raro",
    }
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    got = sources.youtube_channel_videos("@Ibai", "streams")
    assert got["missingTab"] is True and got["videos"] == [] and got["profile"]["name"] == "Luisito Comunica"
    with pytest.raises(SourceError, match="No existe el canal"):
        sources.youtube_channel_videos("@Nadie", "videos")
    with pytest.raises(SourceError, match="No se pudo leer el canal"):
        sources.youtube_channel_videos("@Roto", "videos")
    assert sources.youtube_channel_videos("@Ibai", "otra-cosa")["tab"] == "videos"  # pestaña desconocida → videos


def test_key_includes_the_range():
    yt = sources.parse("https://youtu.be/dQw4w9WgXcQ")
    assert sources.key(yt) == "yt-dQw4w9WgXcQ"
    kick = sources.parse(f"https://kick.com/westcol/videos/{UUID}")
    assert sources.key(kick) == "kick-01a0e42001d077c88e8fb8e88cdff2d4"
    assert sources.key(kick, 600, 780.9) == "kick-01a0e42001d077c88e8fb8e88cdff2d4-s600-e780"
    assert sources.key(kick, 0, 900) != sources.key(kick, 600, 1500) != sources.key(kick)
    assert sources.key(sources.parse("https://kick.com/westcol")) is None and sources.key({}) is None


def test_check_range_validates():
    assert sources.check_range(None, None, 240) is None and sources.check_range("", "", 240) is None
    assert sources.check_range(600, 1500, 240) == (600.0, 1500.0) and sources.check_range(None, 900, 240) == (0.0, 900.0)
    with pytest.raises(SourceError, match="después del inicio"):
        sources.check_range(900, 600, 240)
    with pytest.raises(SourceError, match="al menos 60"):
        sources.check_range(0, 30, 240)
    with pytest.raises(SourceError, match="máximo es 240"):
        sources.check_range(0, 5 * 3600, 240)
    with pytest.raises(SourceError, match="inicio y un fin"):
        sources.check_range(10, "abc", 240)


def test_apply_range_rebases_info():
    info = {"duration": 5400, "chapters": [{"start_time": 0, "end_time": 700, "title": "a"},
                                           {"start_time": 700, "end_time": 1500, "title": "b"},
                                           {"start_time": 1500, "end_time": 5400, "title": "c"}],
            "heatmap": [{"start_time": 500, "end_time": 600, "value": .5}, {"start_time": 900, "end_time": 1000, "value": 1.0},
                        {"start_time": 3000, "end_time": 3100, "value": .2}]}
    out = sources.apply_range(info, 600, 1200)
    assert out["duration"] == 600 and out["full_duration"] == 5400 and out["range"] == {"start": 600, "end": 1200}
    assert [(c["title"], c["start_time"], c["end_time"]) for c in out["chapters"]] == [("a", 0, 100), ("b", 100, 600)]
    assert [(h["start_time"], h["end_time"], h["value"]) for h in out["heatmap"]] == [(300, 400, 1.0)]  # solo el pico que cae en el tramo, corrido
    assert info["duration"] == 5400                                        # no toca el original
    none = sources.apply_range({"duration": 100}, 0, 60)
    assert none["chapters"] == [] and none["heatmap"] is None


def test_kick_channel_vods_parses_the_public_api(monkeypatch):
    payload = [{"created_at": "2026-09-27 18:28:20", "session_title": "TEMA", "is_live": False, "duration": 2723000,
                "views": 412848, "thumbnail": {"src": "https://x/t.jpg"}, "video": {"uuid": UUID}},
               {"created_at": "2026-09-29 20:09:24", "session_title": "EN VIVO", "is_live": True, "duration": 0,
                "video": {"uuid": "4a480fe6-e723-408d-a72b-aeb2c39901c4"}},
               {"session_title": "sin uuid", "video": {}}]

    profile = {"user": {"username": "Westcol", "profile_pic": "https://x/a.webp"}, "followers_count": "4145257",
               "verified": True, "livestream": {"session_title": "EN VIVO"}}
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: profile if "/channels/westcol" in url and "videos" not in url else payload)
    got = sources.kick_channel_vods("westcol")
    assert got["profile"] == {"name": "Westcol", "avatar": "https://x/a.webp", "followers": 4145257, "verified": True,
                              "live": "EN VIVO"}
    assert [v["id"] for v in got["vods"]] == [UUID, "4a480fe6-e723-408d-a72b-aeb2c39901c4"]
    first = got["vods"][0]
    assert first["url"] == f"https://kick.com/westcol/videos/{UUID}" and first["durationSec"] == 2723
    assert first["createdAt"] == "2026-09-27" and first["thumbnail"] == "https://x/t.jpg" and got["vods"][1]["live"] is True
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: None)
    with pytest.raises(SourceError, match="No existe el canal"):
        sources.kick_channel_vods("nadie")
    assert sources.kick_profile("nadie") is None                       # sin perfil, los VODs se listan igual
    def boom(url, what):
        raise SourceError("caído")
    monkeypatch.setattr(sources, "_kick_json", boom)
    assert sources.kick_profile("westcol") is None


def test_canonical_url_resolves_the_channel(monkeypatch):
    with_channel = sources.parse(f"https://kick.com/westcol/videos/{UUID}")
    assert sources.canonical_url(with_channel) == f"https://kick.com/westcol/videos/{UUID}"      # sin consultar nada
    bare = sources.parse(f"https://kick.com/video/{UUID}")
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: {"livestream": {"channel": {"slug": "westcol"}}})
    assert sources.canonical_url(bare) == f"https://kick.com/westcol/videos/{UUID}"
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: None)
    with pytest.raises(SourceError, match="ya no existe"):
        sources.canonical_url(bare)
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: {"deleted_at": "2026-09-01", "livestream": {}})
    with pytest.raises(SourceError, match="ya no existe"):
        sources.canonical_url(bare)
    monkeypatch.setattr(sources, "_kick_json", lambda url, what: {"livestream": {}})
    with pytest.raises(SourceError, match="de qué canal"):
        sources.canonical_url(bare)


# ── Descarga: validaciones antes de tocar la red ─────────────────────────────

def _project(url, start=None, end=None, kind="kick"):
    return {"id": "p" * 20, "sourceType": kind, "sourceUrl": url, "rangeStartSec": start, "rangeEndSec": end}


def test_download_rejects_channels_clips_unknown_sites_and_bad_ranges(tmp_path):
    from media.errors import PermanentError
    from media.tasks import download

    with pytest.raises(PermanentError, match="clip o de un canal"):
        download._download_remote(_project("https://kick.com/westcol"), tmp_path)
    with pytest.raises(PermanentError, match="clip o de un canal"):
        download._download_remote(_project("https://kick.com/westcol?clip=clip_01ABC"), tmp_path)
    with pytest.raises(PermanentError, match="ni de Kick"):
        download._download_remote(_project("https://vimeo.com/1"), tmp_path)
    with pytest.raises(PermanentError, match="lista|canal|búsqueda"):
        download._download_remote(_project("https://www.youtube.com/playlist?list=PL1", kind="youtube"), tmp_path)
    good = f"https://kick.com/westcol/videos/{UUID}"
    with pytest.raises(PermanentError, match="después del inicio"):
        download._download_remote(_project(good, 900, 600), tmp_path)
    with pytest.raises(PermanentError, match="máximo es"):
        download._download_remote(_project(good, 0, 99 * 3600), tmp_path)


def test_kick_format_ladder_prefers_h264_up_to_1080p_and_accepts_muxed_hls():
    from media.tasks import download
    ladder = download.KICK_FORMAT_LADDER.split("/")
    assert ladder[0].startswith("bv*[vcodec^=avc1][height<=1080]+ba")
    assert any(part.startswith("b[") for part in ladder)          # un HLS con video y audio juntos también sirve
    assert ladder[-1] == "best" and download.KICK_CHAIN == (None, None)


def test_project_key_for_kick_includes_the_range(temp_db):
    from media.services import source_cache
    folder = temp_db.parent / "projects" / "x"
    folder.mkdir(parents=True)
    kick = sources.parse(f"https://kick.com/westcol/videos/{UUID}")
    source_cache.remember_key(folder, sources.key(kick, 600, 960))
    assert source_cache.project_key({"sourceType": "kick"}, folder) == "kick-01a0e42001d077c88e8fb8e88cdff2d4-s600-e960"
