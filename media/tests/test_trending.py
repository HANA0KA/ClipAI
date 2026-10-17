"""Tendencias: filtros de búsqueda, puntaje de potencial para clips y descubrimiento (sin red)."""
import base64
import time
from urllib.parse import unquote

import pytest

from media.config import reset_settings
from media.services import trending as tr

NOW = 1_790_000_000.0
DAY = 86400


def card(**kw):
    base = {"id": "abcdefghijk", "title": "Episodio 12 | Entrevista", "channel": "Canal", "views": 1_000_000,
            "likes": 40_000, "comments": 3000, "timestamp": NOW - 3 * DAY, "duration": 5400, "followers": 1_000_000,
            "chapters": 10, "subs_manual": False, "subs_auto": True, "live_status": "not_live", "age_limit": 0,
            "availability": "public", "partial": False}
    return {**base, **kw}


# ── Búsqueda ─────────────────────────────────────────────────────────────────

def test_search_filter_matches_youtube_protobuf():
    # esta semana + video + más de 20 min + orden por vistas: el valor que acepta YouTube
    assert unquote(tr.search_filter("views", "week", "long")) == "CAMSBggDEAEYAg=="
    raw = base64.urlsafe_b64decode(unquote(tr.search_filter("views", "week", "long")))
    assert raw == bytes([0x08, 3, 0x12, 6, 0x08, 3, 0x10, 1, 0x18, 2])
    assert unquote(tr.search_filter("relevance", None, None)) == "EgIQAQ=="       # solo «tipo: video»
    assert unquote(tr.search_filter("date", "day", None)) == "CAISBAgCEAE="
    assert "search_query=podcast%20entrevista&sp=" in tr.search_url(" podcast entrevista ", "views", "week", "long")


# ── Puntaje ──────────────────────────────────────────────────────────────────

def test_hot_long_chaptered_conversation_scores_very_high_with_reasons():
    out = tr.score(card(views=5_000_000, likes=130_000, timestamp=NOW - 5 * DAY, chapters=15, subs_manual=True), NOW, 240)
    assert out["score"] >= 78 and out["tier"] == "muy alto"
    text = " | ".join(out["reasons"])
    assert "por día" in text and "capítulos" in text and "Subtítulos del creador" in text
    assert out["warnings"] == [] and set(out["parts"]) == {"momentum", "outperform", "engagement", "clips"}


def test_unremarkable_video_scores_low():
    dull = tr.score(card(views=8_000, likes=100, comments=5, timestamp=NOW - 90 * DAY, duration=420, chapters=0,
                         subs_auto=False, followers=500_000, title="Vlog de hoy"), NOW, 240)
    hot = tr.score(card(), NOW, 240)
    assert dull["score"] < 35 and dull["tier"] == "bajo" and hot["score"] > dull["score"] + 40
    assert any("Sin subtítulos" in w for w in dull["warnings"]) and any("reciente" in w for w in dull["warnings"])


def test_momentum_outperformance_and_material_each_move_the_score():
    base = tr.score(card(), NOW, 240)["score"]
    assert tr.score(card(views=100_000), NOW, 240)["score"] < base                       # menos impulso
    assert tr.score(card(timestamp=NOW - 40 * DAY), NOW, 240)["score"] < base            # más viejo = menos por día
    assert tr.score(card(followers=50_000_000), NOW, 240)["score"] < base                # no se sale de su público
    assert tr.score(card(chapters=0), NOW, 240)["score"] < base
    assert tr.score(card(duration=900), NOW, 240)["score"] < base                        # poca duración
    assert tr.score(card(subs_auto=False), NOW, 240)["score"] < base
    r = tr.score(card(views=3_000_000, followers=1_000_000), NOW, 240)["reasons"]
    assert any("más vistas que suscriptores" in x for x in r)


def test_missing_data_is_neutral_not_a_crash():
    out = tr.score(card(timestamp=None, likes=None, comments=None, followers=None, partial=True), NOW, 240)
    assert 0 <= out["score"] <= 100
    tr.score({"views": None, "duration": None}, NOW, 240)  # ficha casi vacía


def test_too_long_video_warns_and_gets_no_duration_points():
    out = tr.score(card(duration=6 * 3600), NOW, 240)
    assert any("supera el máximo de 240 min" in w for w in out["warnings"])
    assert out["parts"]["clips"] < tr.score(card(), NOW, 240)["parts"]["clips"]


def test_excluded_reasons():
    assert tr.excluded(card(), 240) is None and tr.excluded(card(availability=None), 240) is None
    assert tr.excluded(card(live_status="is_live"), 240) == "en directo"
    assert tr.excluded(card(live_status="is_upcoming"), 240) == "en directo"
    assert tr.excluded(card(live_status="was_live"), 240) is None                          # un directo ya terminado sirve
    assert tr.excluded(card(duration=120), 240) == "muy corto"
    assert tr.excluded(card(duration=5 * 3600), 240) == "demasiado largo"
    assert tr.excluded(card(duration=None), 240) == "sin duración"
    assert tr.excluded(card(age_limit=18), 240) == "solo adultos"
    assert tr.excluded(card(availability="needs_auth"), 240) == "no es público"


def test_formatters_in_spanish():
    assert [tr.fmt_count(n) for n in (950, 1500, 12_300, 845_000, 3_200_000, 5_850_939, 120_000_000)] == \
        ["950", "1,5 mil", "12 mil", "845 mil", "3,2 M", "5,9 M", "120 M"]
    assert tr.fmt_span(0.01) == "unas horas" and tr.fmt_span(0.5) == "menos de un día"
    assert tr.fmt_span(1) == "1 día" and tr.fmt_span(5.2) == "5 días" and tr.fmt_span(90) == "3 meses"
    assert tr.fmt_duration(3300) == "55 min" and tr.fmt_duration(10767) == "2 h 59 min"


def test_spoken_language_and_real_subtitles():
    assert tr.spoken_language({"automatic_captions": {"en": [1], "es-orig": [1], "pt": [1]}}) == "es"
    assert tr.spoken_language({"automatic_captions": {"es-419-orig": [1]}}) == "es"
    assert tr.spoken_language({"language": "pt-BR"}) == "pt" and tr.spoken_language({}) is None
    assert tr.real_subtitles({"subtitles": {"es": [1]}}) is True
    assert tr.real_subtitles({"subtitles": {"live_chat": [1]}}) is False      # el chat de un directo no son subtítulos
    assert tr.real_subtitles({}) is False


def test_wrong_script_only_for_latin_alphabet_languages():
    assert tr.wrong_script("Bharti के पेट में Harssh को दिखे 9 Burger", "es") is True         # mezcla con mucho hindi
    assert tr.wrong_script("Mi viaje a Japón: 東京 en 5 días, ¡increíble!", "es") is False    # una palabra suelta no basta
    assert tr.wrong_script("भारती के पेट में हर्ष को दिखे बर्गर", "es") is True
    assert tr.wrong_script("Подкаст о жизни и деньгах", "en") is True
    assert tr.wrong_script("¡ROMPE EL SILENCIO! Entrevista", "es") is False
    assert tr.wrong_script("भारती के पेट में", "hi") is False and tr.wrong_script("भारती के पेट में", None) is False
    assert tr.wrong_script("Ok", "es") is False                                            # muy corto para decidir


def test_resolve_lang(temp_db, monkeypatch):
    assert tr.resolve_lang("auto") == "es" and tr.resolve_lang(None) == "es"
    assert tr.resolve_lang("EN") == "en" and tr.resolve_lang("pt-BR") == "pt" and tr.resolve_lang("any") is None
    monkeypatch.setenv("TRENDING_LANG", "any")
    reset_settings()
    assert tr.resolve_lang("auto") is None


def test_normalize_prefers_full_card_and_ignores_tiny_follower_counts():
    flat = {"id": "abcdefghijk", "title": "Plano", "channel": "C", "view_count": 10, "duration": 100}
    full = {"title": "Completo", "view_count": 99, "like_count": 5, "channel_follower_count": 20,
            "chapters": [{}, {}], "subtitles": {"es": [1]}, "timestamp": 5, "duration": 3600}
    got = tr.normalize(flat, full)
    assert got["title"] == "Completo" and got["views"] == 99 and got["followers"] is None and got["chapters"] == 2
    assert got["subs_manual"] and not got["partial"]
    part = tr.normalize(flat, None)
    assert part["partial"] and part["views"] == 10 and part["duration"] == 100


# ── Descubrir (con YouTube simulado) ─────────────────────────────────────────

def _fake(monkeypatch, calls):
    def fake_search(q, sort, period, duration, count):
        calls["search"].append((q, sort, period, duration, count))
        if q == "roto":
            raise tr.TrendingError("La búsqueda «roto» falló")
        return [{"id": f"{q[:1]}{i:010d}"[:11], "title": f"{q} {i}", "view_count": 1000 * (10 - i), "duration": 3600}
                for i in range(3)] + ([{"id": "compartido1", "title": "x", "view_count": 5, "duration": 3600}])

    def fake_details(vid):
        calls["details"].append(vid)
        if vid.startswith("z"):
            return None
        short = vid == "compartido1"
        english = vid.startswith("b")
        return {"title": f"T {vid}", "view_count": 2_000_000, "like_count": 60_000, "comment_count": 4000,
                "timestamp": time.time() - 2 * DAY, "duration": 90 if short else 5400, "channel": "C",
                "channel_follower_count": 1_000_000, "chapters": [{}] * 6,
                "automatic_captions": {"en-orig" if english else "es-orig": [1]}}
    monkeypatch.setattr(tr, "search", fake_search)
    monkeypatch.setattr(tr, "details", fake_details)


def test_discover_merges_topics_dedupes_scores_and_caches(temp_db, monkeypatch):
    calls = {"search": [], "details": []}
    _fake(monkeypatch, calls)
    out = tr.discover(None, topics=["alfa", "beta"], limit=10, lang="any")
    assert sorted(q for q, *_ in calls["search"]) == ["alfa", "beta"]
    ids = [i["id"] for i in out["items"]]
    assert len(ids) == len(set(ids)) and "compartido1" not in ids                      # duplicado una vez y luego oculto: 90 s
    assert out["meta"]["hidden"] == {"muy corto": 1} and out["meta"]["cached"] is False
    assert all(i["reasons"] and 0 <= i["score"] <= 100 and i["thumbnail"].endswith("/hqdefault.jpg") for i in out["items"])
    assert [i["score"] for i in out["items"]] == sorted((i["score"] for i in out["items"]), reverse=True)
    n = len(calls["search"])
    again = tr.discover(None, topics=["alfa", "beta"], limit=10, lang="any")
    assert again["meta"]["cached"] is True and len(calls["search"]) == n               # sin volver a YouTube
    tr.discover(None, topics=["alfa", "beta"], limit=10, refresh=True, lang="any")
    assert len(calls["search"]) == n + 2


def test_discover_single_query_uses_it_and_survives_partial_failures(temp_db, monkeypatch):
    calls = {"search": [], "details": []}
    _fake(monkeypatch, calls)
    out = tr.discover("beta", period="month", sort="date", duration=None, per_query=5)
    assert calls["search"] == [("beta", "date", "month", None, 5)] and out["meta"]["queries"] == ["beta"]
    both = tr.discover(None, topics=["roto", "alfa"])                                    # un tema falla, el otro sirve
    assert both["items"]
    with pytest.raises(tr.TrendingError, match="roto"):
        tr.discover("roto")


def test_discover_keeps_partial_cards_when_details_fail(temp_db, monkeypatch):
    calls = {"search": [], "details": []}
    _fake(monkeypatch, calls)
    out = tr.discover("zeta", duration="long")
    assert out["items"] and all(i["partial"] for i in out["items"])                     # sin ficha: puntúa con lo que hay
    assert tr.discover("zeta", duration="long")["meta"]["cached"] is True


def test_default_topics_come_from_env(temp_db, monkeypatch):
    monkeypatch.setenv("TRENDING_TOPICS", " uno , dos ,, ")
    reset_settings()
    assert tr.default_topics() == ["uno", "dos"]
    monkeypatch.delenv("TRENDING_TOPICS")
    reset_settings()
    assert "podcast" in tr.default_topics()


def test_trending_endpoint_validates_and_maps_errors(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from media.main import app
    calls = {"search": [], "details": []}
    _fake(monkeypatch, calls)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/trending?period=siglo").status_code == 400
        ok = client.get("/trending?q=beta&duration=any&period=day&lang=any")
        assert ok.status_code == 200 and ok.json()["items"] and "podcast" in ok.json()["topics"]
        assert ok.json()["defaultLang"] == "es"
        assert calls["search"][-1][3] is None                                            # «any» = sin filtro de duración
        bad = client.get("/trending?q=roto&lang=any")
        assert bad.status_code == 502 and "roto" in bad.json()["detail"]


def test_discover_filters_by_spoken_language(temp_db, monkeypatch):
    calls = {"search": [], "details": []}
    _fake(monkeypatch, calls)
    spanish = tr.discover(None, topics=["alfa", "beta"], lang="auto")
    assert spanish["meta"]["lang"] == "es" and spanish["meta"]["hidden"].get("otro idioma", 0) > 0
    assert all(i["language"] == "es" for i in spanish["items"])
    anyl = tr.discover(None, topics=["alfa", "beta"], lang="any")
    assert anyl["meta"]["lang"] is None and {i["language"] for i in anyl["items"]} == {"es", "en"}
    english = tr.discover(None, topics=["alfa", "beta"], lang="en")
    assert english["items"] and all(i["language"] == "en" for i in english["items"])   # el filtro entra en la clave de la caché
