"""Portada con el gancho en grande y hashtags del canal (creador + fijos)."""
import json

import pytest

from media.config import reset_settings
from media.services import ass_builder, cover, hashtags


def _measure(text, size):
    return len(text) * size * 0.6


# ── Ajustes ──────────────────────────────────────────────────────────────────

def test_parse_defaults_and_invalid_values():
    assert cover.parse(None) == cover.DEFAULTS
    got = cover.parse('{"text": "  Hola  ", "time": -3, "position": "left", "style": "neon", "dim": "no"}')
    assert got == {**cover.DEFAULTS, "text": "Hola"}
    assert cover.parse("no es json") == cover.DEFAULTS
    assert cover.parse({"text": "", "time": "12.5", "position": "top"})["text"] is None
    assert cover.parse({"time": "12.5"})["time"] == 12.5


def test_merge_only_touches_given_keys():
    saved = json.dumps({"text": "Mi texto", "time": 40.0, "position": "bottom", "style": "box", "dim": False})
    assert cover.merge(saved, {"position": "top"}) == {"text": "Mi texto", "time": 40.0, "position": "top",
                                                       "style": "box", "dim": False}
    back = cover.merge(saved, {"text": None, "time": None, "junk": 1})  # null = volver a lo automático
    assert back["text"] is None and back["time"] is None and back["style"] == "box"


def test_clip_offset_maps_source_time_to_clip():
    parts = [(140.0, 143.0), (100.0, 170.0)]  # avance delante
    assert cover.clip_offset(parts, 141.0) == pytest.approx(1.0)
    assert cover.clip_offset(parts, 120.0) == pytest.approx(23.0)
    assert cover.clip_offset(parts, 90.0) is None and cover.clip_offset(parts, None) is None


# ── Texto ────────────────────────────────────────────────────────────────────

def test_split_balanced_minimizes_longest_line():
    words = "EL ERROR DE 40 MIL DÓLARES QUE CASI TODOS COMETEN".split()
    lines = cover.split_balanced(words, 3, lambda t: len(t))
    assert len(lines) == 3 and " ".join(lines) == " ".join(words)
    assert max(map(len, lines)) <= 18


def test_fit_text_prefers_biggest_size_that_fits():
    lines, size = cover.fit_text("NADIE TE ESCUCHA", measure=_measure, max_width=920, max_height=1300,
                                 size_max=150, size_min=70)
    assert size == 150 and lines == ["NADIE TE", "ESCUCHA"]
    long = "UNA FRASE MUCHO MÁS LARGA QUE NO CABE EN POCAS LÍNEAS NUNCA"
    lines, size = cover.fit_text(long, measure=_measure, max_width=920, max_height=1300, size_max=150, size_min=70)
    assert len(lines) <= cover.MAX_LINES and size < 150
    assert all(_measure(x, size) <= 920 + 1e-6 for x in lines)


def test_accent_words_numbers_power_words_or_longest():
    assert 3 in cover.accent_words("EL ERROR DE 40 MIL".split())
    assert cover.accent_words("LA REGLA DE ORO PARA COMUNICARTE".split()) == {5}  # la más larga


def test_build_ass_positions_styles_and_safe_zone():
    tpl = ass_builder.load_template("bold-yellow")
    ass, block = cover.build_ass("Por qué nos encanta que nos escuchen", tpl=tpl, width=1080, height=1920)
    assert "\\an5\\pos(540,960)" in ass and "WrapStyle: 2" in ass and "POR QUÉ" in ass
    center, h = block
    assert center == 960 and 1920 * cover.SAFE_TOP <= center - h / 2 and center + h / 2 <= 1920 * cover.SAFE_BOTTOM
    top, _ = cover.build_ass("Nadie te escucha", tpl=tpl, width=1080, height=1920, position="top")
    assert "\\an8\\pos(540,307.2)" in top
    box, _ = cover.build_ass("Nadie te escucha", tpl=tpl, width=1080, height=1920, style="box", position="bottom")
    assert "\\an2" in box and ",3," in box.split("Style: Cover,")[1].split("\n")[0]  # caja (BorderStyle 3)
    assert cover.build_ass("  ", tpl=tpl, width=1080, height=1920) == ("", None)


def test_command_and_band_filter():
    cmd = cover.command("reframed.mp4", 12.5, "cover.tmp.jpg", width=1080, height=1920, ass="cover.ass",
                        fonts_rel="../fonts", effects=None, band=(960.0, 400.0))
    vf = cmd[cmd.index("-vf") + 1]
    assert cmd[cmd.index("-ss") + 1] == "12.500" and "-frames:v" in cmd
    assert "geq=lum=" in vf and "ass=cover.ass:fontsdir=../fonts" in vf and vf.endswith("format=yuvj420p")
    plain = cover.command("reframed.mp4", 0, "o.jpg", width=1080, height=1080, ass=None, fonts_rel="f",
                          effects=None, band=None)
    assert "geq" not in plain[plain.index("-vf") + 1]


def test_filename_from_hook():
    assert cover.filename({"hook": "¿Por qué nadie te escucha?"}) == "portada-por-qué-nadie-te-escucha.jpg"
    assert cover.filename({}) == "portada-clip.jpg"


# ── Hashtags del canal ───────────────────────────────────────────────────────

def test_creator_and_base_tags():
    assert hashtags.creator_tag({"channel": "Luisito Comunica"}) == "#LuisitoComunica"
    assert hashtags.creator_tag({"channel": "Artista - Topic"}) == "#Artista"
    assert hashtags.creator_tag({"uploader_id": "@clavero"}) == "#clavero"
    assert hashtags.creator_tag({}) is None and hashtags.creator_tag(None) is None
    assert hashtags.base_tags("#YoutubersEspañoles #Streamers, streamers") == ["#YoutubersEspañoles", "#Streamers"]
    assert hashtags.base_tags("0") == []


def test_apply_niche_caps_order_and_idempotence():
    sets = {"tiktok": ["#parati", "#Viajes", "#Japón", "#Comida", "#Curiosidades"],
            "instagram": ["#Viajes", "#Japón", "#Comida", "#Curiosidades", "#reels"],
            "youtube": ["#Shorts", "#Viajes", "#Japón", "#Comida"]}
    lead, tail = ["#LuisitoComunica"], ["#YoutubersEspañoles", "#Streamers"]
    got = hashtags.apply_niche(sets, lead, tail)
    assert got["instagram"] == ["#LuisitoComunica", "#Viajes", "#Japón", "#YoutubersEspañoles", "#Streamers"]
    assert got["youtube"][:3] == ["#Shorts", "#LuisitoComunica", "#Viajes"] and got["youtube"][-1] == "#Streamers"
    assert all(len([t for t in got[p] if t != "#Shorts"]) <= hashtags.CAPS[p] for p in hashtags.PLATFORMS)
    assert hashtags.apply_niche(got, lead, tail) == got
    many = hashtags.apply_niche(sets, lead, ["#a1", "#b2", "#c3", "#d4"])  # fijas de sobra: se recortan
    assert many["instagram"][1:3] == ["#Viajes", "#Japón"] and len(many["instagram"]) == 5
    assert hashtags.apply_niche(sets) == sets


def test_apply_niche_line_for_kit():
    line = hashtags.apply_niche_line("#streamers #ibai #risas #directo", ["#Ibai"], ["#YoutubersEspañoles", "#Streamers"])
    assert line == "#Ibai #risas #directo #YoutubersEspañoles #Streamers"


def test_with_channel_tags_reads_channel_and_settings(tmp_path, monkeypatch):
    from media.tasks.analyze import with_channel_tags
    (tmp_path / "source.info.json").write_text(json.dumps({"channel": "Ibai"}), encoding="utf-8")
    result = {"clips": [{"hashtags": "#risas #directo", "hashtagSets": json.dumps(
        {"tiktok": ["#risas"], "instagram": ["#risas"], "youtube": ["#Shorts", "#risas"]})}]}
    monkeypatch.setenv("HASHTAGS_BASE", "#YoutubersEspañoles #Streamers")
    monkeypatch.setenv("HASHTAGS_CREATOR", "1")
    reset_settings()
    try:
        clip = with_channel_tags(result, tmp_path)["clips"][0]
        # el creador y el formato (#Clips) van delante
        assert clip["hashtags"] == "#Ibai #Clips #risas #directo #YoutubersEspañoles #Streamers"
        assert json.loads(clip["hashtagSets"])["youtube"] == ["#Shorts", "#Ibai", "#Clips", "#risas", "#YoutubersEspañoles", "#Streamers"]
        monkeypatch.setenv("HASHTAGS_BASE", "0")
        monkeypatch.setenv("HASHTAGS_CREATOR", "0")
        monkeypatch.setenv("HASHTAGS_FORMAT", "0")
        reset_settings()
        assert with_channel_tags(result, tmp_path) == result
    finally:
        reset_settings()


def test_cover_request_validation():
    from fastapi.testclient import TestClient
    from media import main
    c = TestClient(main.app, base_url="http://127.0.0.1:8000")
    assert c.post("/clips/abc/cover", json={"position": "left"}).status_code == 422
    assert c.post("/clips/abc/cover", json={"time": -1}).status_code == 422


def test_rendered_parts_follow_last_reframe(tmp_path):
    assert cover.rendered_parts(tmp_path) is None
    (tmp_path / "reframe.json").write_text(json.dumps({"parts": [[25.39, 95.76]], "mode": "auto"}), encoding="utf-8")
    assert cover.rendered_parts(tmp_path) == [(25.39, 95.76)]
    (tmp_path / "reframe.json").write_text(json.dumps({"parts": [["x", 1]]}), encoding="utf-8")
    assert cover.rendered_parts(tmp_path) is None


def test_make_cover_requires_render(tmp_path):
    with pytest.raises(cover.CoverError):
        cover.make_cover({"id": "c1", "startSec": 0, "endSec": 60}, tmp_path)


def test_prompts_know_the_original_video():
    from media.services import story_arc
    label = hashtags.video_label({"title": "Ibai y Luisito en Japón", "channel": "Ibai"})
    assert label == "Ibai y Luisito en Japón · canal Ibai"
    assert hashtags.video_label({}, "subido.mp4") == "subido.mp4" and hashtags.video_label(None) == ""
    assert "VIDEO ORIGINAL: Ibai y Luisito en Japón · canal Ibai" in hashtags.build_prompt("hola", "t", "g", "es", label)
    assert "VIDEO ORIGINAL: -" in hashtags.build_prompt("hola", "t", "g", "es")
    arc = story_arc.build_arc_prompt([{"start": 0, "end": 60}], [], "es", 60, 150, 100, video=label)
    assert "VIDEO ORIGINAL: Ibai y Luisito en Japón" in arc and "#Ibai" in arc


def test_apply_niche_keeps_people_from_the_video_title():
    sets = {"tiktok": ["#ComunicacionEfectiva", "#EscuchaActiva", "#VictorKüppers", "#Empatia"],
            "instagram": ["#EscuchaActiva", "#Empatia", "#Liderazgo", "#VictorKüppers"],
            "youtube": ["#Shorts", "#EscuchaActiva", "#VictorKüppers"]}
    got = hashtags.apply_niche(sets, ["#AprendemosJuntos"], ["#YoutubersEspañoles", "#Streamers"],
                               prefer="Victor Küppers: Por qué es tan importante aprender a escuchar")
    assert all(got[p][(1 if p == "youtube" else 0) + 1] == "#VictorKüppers" for p in hashtags.PLATFORMS)
    assert got["instagram"] == ["#AprendemosJuntos", "#VictorKüppers", "#EscuchaActiva", "#YoutubersEspañoles",
                                "#Streamers"]
