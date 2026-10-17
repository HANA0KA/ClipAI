"""Duración 60–70 s, gancho, subtítulos estilo OpusClip, estudio de edición,
render, caché por fuente, línea de tiempo, fuentes y cancelación."""
import json
import re
import wave

import numpy as np
import pytest

from media.config import settings
from media.services import (ass_builder, caption_fx, cut_ops, db, edit_doc, fonts, scoring,
                            source_cache, timeline_assets)
from media.services.candidates import pause_before
from media.services.moments import Judged, classify_hook, normalize_hook_type, sanitize_hook


def _words(text, t0=0.0, step=0.5, dur=0.4):
    return [{"w": w, "start": round(t0 + i * step, 3), "end": round(t0 + i * step + dur, 3)}
            for i, w in enumerate(text.split())]


def _sentences(n, t0=0.0, words_per=8, step=0.5):
    """n frases de ``words_per`` palabras (la última con punto)."""
    text = " ".join(" ".join(["palabra"] * (words_per - 1) + ["fin."]) for _ in range(n))
    return _words(text, t0, step)


# ── Duración ─────────────────────────────────────────────────────────────────

def test_fit_duration_trims_long_clip_to_sentence_end():
    words = _sentences(25)  # frases de 4 s
    s, e, path = cut_ops.fit_duration(0.0, 95.0, words, lo=60, hi=70, target=70)
    assert path == "trim_sentence" and 60 <= e - s <= 70
    assert any(abs(e - (w["end"] + cut_ops.DEFAULT_POST_PAD)) < 1e-6 for w in words if w["w"] == "fin.")


def test_fit_duration_extends_short_clip_towards_target():
    words = _sentences(25)
    s, e, path = cut_ops.fit_duration(0.0, 40.0, words, lo=60, hi=70, target=70)
    assert path == "extend_sentence" and 60 <= e - s <= 70 and e - s > 67


def test_fit_duration_keeps_valid_and_moves_start_near_video_end():
    words = _sentences(25)
    assert cut_ops.fit_duration(0.0, 65.0, words, lo=60, hi=70)[2] == "none"
    total = words[-1]["end"]
    s, e, path = cut_ops.fit_duration(total - 30, total + 0.08, words, lo=60, hi=70, source_duration=total + 0.08)
    assert path == "extend_start" and e - s >= 60 - 1e-6 and s >= 0


def test_fit_duration_without_punctuation_uses_word_ends():
    words = _words(" ".join(["hola"] * 200), step=0.5)
    s, e, path = cut_ops.fit_duration(0.0, 80.0, words, lo=60, hi=70)
    assert path == "trim_word" and 60 <= e - s <= 70


# ── Gancho ───────────────────────────────────────────────────────────────────

def test_sanitize_hook_quotes_hashtags_and_limits():
    assert sanitize_hook('"El error de 40 mil" #finanzas #shorts') == "El error de 40 mil"
    assert sanitize_hook("«Nadie» te lo dice…") == "Nadie te lo dice…"
    assert sanitize_hook("'Don't do this' ’now’") == "Don't do this now"
    long = "uno dos tres cuatro cinco seis siete ocho nueve diez once doce"
    assert sanitize_hook(long) == "uno dos tres cuatro cinco seis siete ocho nueve diez"
    out = sanitize_hook("palabralarga " * 12)
    assert len(out) <= 64 and not out.endswith(" ")
    assert sanitize_hook("¿Por qué nadie habla de esto que es muy importante para los que invierten hoy?") \
        .startswith("Por qué")  # el recorte se comió el «?»: fuera el «¿» huérfano
    assert sanitize_hook("  #solo #hashtags ") == ""


def test_hook_type_rules_and_aliases():
    assert classify_hook("¿Sabías esto?") == "question"
    assert classify_hook("El 90% de la gente falla") == "statistic"
    assert classify_hook("Hace años me pasó algo increíble") == "story"
    assert classify_hook("No es talento, es disciplina") == "contrast"
    assert classify_hook("Esto cambia todo") == "statement"
    assert normalize_hook_type("Estadística") == "statistic" and normalize_hook_type("xyz") is None
    j = Judged(id=0, start="1:00", end=70, hook=5, story=5, value=5, engagement=5, reach=5, hook_type="Pregunta")
    assert j.hook_type == "question"


def test_pause_signal_and_hook_bonus():
    words = [{"w": "a", "start": 0.5, "end": 0.9}, {"w": "b", "start": 1.0, "end": 1.4},
             {"w": "c", "start": 2.6, "end": 3.0}, {"w": "d", "start": 3.6, "end": 3.9}]
    assert pause_before(words, 2.6) == 1.0 and pause_before(words, 3.6) == 0.5 and pause_before(words, 1.0) == 0
    assert scoring.hook_signal({"hook": 0.5, "pause": 1.0}) == pytest.approx(0.7)
    assert scoring.hook_signal({"hook": 0.95, "pause": 1.0}) == 1.0
    j = {"hook": 5, "story": 5, "value": 5, "engagement": 5, "reach": 5}
    assert scoring.final_score(j, {"heat": None, "audio": 0, "hook": 0.5, "pause": 1}) > \
        scoring.final_score(j, {"heat": None, "audio": 0, "hook": 0.5, "pause": 0})


# ── Énfasis y emojis ─────────────────────────────────────────────────────────

def test_annotate_emphasis_numbers_manual_and_emoji_limits():
    words = [{"w": w} for w in "el SECRETO del dinero es que nunca vas a ganar 90% sin tiempo dinero y dinero".split()]
    words[2]["hl"] = True
    emojis, emph = caption_fx.annotate(words, max_emojis=3, min_gap=3, repeat_gap=8)
    assert {1, 2, 3, 6, 10} <= emph  # secreto, marcada, dinero, nunca, 90%
    idx = sorted(emojis)
    assert len(idx) <= 3 and all(b - a >= 3 for a, b in zip(idx, idx[1:]))
    assert caption_fx.lookup_emoji("escuchen") == "👂" and caption_fx.lookup_emoji("dineros") == "💰"
    assert caption_fx.normalize_token("¿Niño?") == "niño"
    assert caption_fx.emoji_budget(70) == 8 and caption_fx.emoji_budget(10) == 1


# ── ASS ──────────────────────────────────────────────────────────────────────

def _dialogues(ass, style):
    return [l for l in ass.splitlines() if l.startswith("Dialogue") and f",{style}," in l]


def test_libass_em_ratio_matches_measured_fonts():
    from media.config import FONTS_DIR
    assert ass_builder.libass_em_ratio(FONTS_DIR / "Montserrat-ExtraBold.ttf") == pytest.approx(1000 / 1562)
    # medido con libass 0.17: «NADIE TE ESCUCHA DE VERDAD» a 100 = 1092 px (Montserrat) y 626 px (Anton)
    assert ass_builder.text_width("NADIE TE ESCUCHA DE VERDAD", "Montserrat ExtraBold", 100) == pytest.approx(1092, rel=0.02)
    assert ass_builder.text_width("NADIE TE ESCUCHA DE VERDAD", "Anton", 100) == pytest.approx(626, rel=0.02)


def test_balance_lines_minimises_longest_line():
    assert ass_builder.balance_lines(["uno", "dos"], len, 100) == ["uno dos"]
    lines = ass_builder.balance_lines("el error de cuarenta mil que casi todos cometen".split(), len, 30)
    assert len(lines) == 2 and max(map(len, lines)) <= 25


def test_hook_two_lines_shrink_and_accent():
    tpl = ass_builder.load_template("bold-yellow")
    one = ass_builder.hook_events("Nadie te escucha", tpl=tpl)
    assert len(one) == 1 and "\\N" not in one[0] and "\\fs" not in one[0]
    two = ass_builder.hook_events("El error de 40 mil dólares que casi todos cometen", tpl=tpl)[0]
    assert two.count("\\N") == 1 and "{\\c&H2828D6&}40{\\c&H111111&}" in two
    huge = ass_builder.hook_events("Antidesestablecimentarismoconstitucionalista", tpl=tpl)[0]
    assert re.search(r"\\fs(\d+)", huge) and int(re.search(r"\\fs(\d+)", huge).group(1)) < 62
    assert ass_builder.hook_events('"#solo"', tpl=tpl) == []


def test_translucent_boxes_on_their_own_layer():
    words = _words("el secreto del dinero es simple")
    ass = ass_builder.build_ass(words, template_id="minimal", hook_text="La verdad", clip_duration=5)
    boxes = _dialogues(ass, "CaptionBox")
    assert boxes and all("{\\c" not in l for l in boxes)  # texto sin cortes: una caja por bloque
    assert "Style: Caption," in ass and ",1,0,0,2," in ass.split("Style: Caption,")[1].splitlines()[0]
    assert len(_dialogues(ass, "HookBox")) == 1 and len(_dialogues(ass, "Hook")) == 1


def test_emphasis_entrance_and_no_word_scaling_in_new_templates():
    words = _words("nunca vas a ganar sin esfuerzo")
    ass = ass_builder.build_ass(words, template_id="tiktok", clip_duration=5)
    caps = _dialogues(ass, "Caption")
    assert "{\\fscx90\\fscy90\\t(0,140,\\fscx100\\fscy100)}" in caps[0]  # entrada una vez por bloque
    assert "\\fscx90" not in caps[1]
    assert "{\\c&HEEF425&}NUNCA" not in caps[0]  # activa: color de resaltado, no de énfasis
    assert "{\\c&HEEF425&}nunca{\\r}" in caps[1]  # «nunca» en énfasis cuando no es la activa
    assert "fscx106" not in "".join(caps)  # sin escalar palabras sueltas


def test_square_output_scales_margins():
    ass = ass_builder.build_ass(_words("hola mundo"), template_id="bold-yellow", width=1080, height=1080)
    assert "PlayResY: 1080" in ass and ",2,80,80,338,1" in ass  # 600 × 1080/1920


def test_plan_emojis_positions_and_budget():
    words = _words("el dinero y el tiempo y la familia y el amor y la salud y el trabajo " * 3)
    plan = ass_builder.plan_emojis(words, template_id="bold-yellow", clip_duration=20)
    assert 1 <= len(plan) <= caption_fx.emoji_budget(20)
    for p in plan:
        assert p["end"] > p["start"] and p["x"] == int(round(540 - p["size"] / 2))
        assert 0 < p["y"] < 1920 - 600  # encima del subtítulo
    assert all(a["end"] <= b["start"] for a, b in zip(plan, plan[1:]))
    assert ass_builder.plan_emojis(words, template_id="minimal") == []


def test_templates_have_hook_accent_and_are_listed():
    ids = {t["id"] for t in ass_builder.list_templates()}
    assert {"bold-yellow", "clean-box", "neon-anton", "hormozi", "mrbeast", "tiktok", "minimal", "podcast"} <= ids
    for tid in ids:
        tpl = ass_builder.load_template(tid)
        assert tpl["hook"].get("accent") and tpl.get("emphasis")


# ── Documento de edición ─────────────────────────────────────────────────────

def test_edit_doc_parse_clamps_and_defaults():
    d = edit_doc.parse('{"segments":[{"start":5,"end":5.1},{"start":10,"end":30}],'
                       '"framing":{"mode":"manual","aspect":"square","zoom":9,"x":-1},'
                       '"effects":{"brightness":999,"hue":"x"},"audio":{"volume":5,"muted":1},'
                       '"preset":"nope","font":"Mala, fuente"}')
    assert d["segments"] == [(10.0, 30.0)]
    assert d["framing"] == {"mode": "manual", "aspect": "square", "fit": "cover", "zoom": 3, "x": 0, "y": 0.5}
    assert d["effects"]["brightness"] == 180 and d["effects"]["hue"] == 0
    assert d["audio"] == {"volume": 2, "muted": True} and d["preset"] == "tiktok" and d["font"] is None
    assert edit_doc.parse("no es json")["segments"] is None


def test_clip_parts_segments_or_legacy_prepend():
    clip = {"startSec": 10, "endSec": 70, "prependBestLine": 1, "bestLineStart": 40, "bestLineEnd": 43}
    assert edit_doc.clip_parts(clip) == [(40.0, 43.0), (10.0, 70.0)]
    clip["edit"] = json.dumps({"segments": [{"start": 30, "end": 50}, {"start": 5, "end": 9}]})
    assert edit_doc.clip_parts(clip) == [(30.0, 50.0), (5.0, 9.0)]


def test_output_size_and_framing_geometry():
    assert edit_doc.output_size("vertical", 1920, 1080) == (1080, 1920)
    assert edit_doc.output_size("square", 1920, 1080) == (1080, 1080)
    assert edit_doc.output_size("original", 3840, 2160) == (1920, 1080)
    g = edit_doc.framing_geometry(1920, 1080, 1080, 1920, "cover", 1.0, 0.5, 0.5)
    assert g["fills"] and g["cx"] == (g["rw"] - 1080) // 2
    g = edit_doc.framing_geometry(1920, 1080, 1080, 1920, "contain", 1.0, 0.5, 0.5)
    assert not g["fills"] and g["cw"] == 1080 and g["oy"] == (1920 - g["ch"]) // 2
    assert "gblur" in edit_doc.framing_filter(1920, 1080, 1080, 1920, {**edit_doc.DEFAULT_FRAMING, "fit": "contain"})


def test_effects_audio_and_preset_filters():
    assert edit_doc.effects_filter(dict(edit_doc.DEFAULT_EFFECTS), 1080) is None
    fx = edit_doc.effects_filter({**edit_doc.DEFAULT_EFFECTS, "brightness": 120, "contrast": 80}, 1080)
    # CSS por canal: v·b·c + 127,5·(1−c) → en YUV limitado: 16 + g·(Y−16) + 219/255·o
    assert "lutyuv=" in fx and "0.9600*(val-16)+21.90" in fx and fx.endswith("format=yuv420p")
    assert "lutrgb" not in fx
    assert edit_doc.audio_filter({"volume": 1.0, "muted": False}) is None
    assert edit_doc.audio_filter({"volume": 1.5, "muted": False}) == "volume=1.500"
    assert edit_doc.audio_filter({"volume": 1.5, "muted": True}) == "volume=0"
    assert edit_doc.maxrate_args("reels") == ["-maxrate", "12M", "-bufsize", "24M"]


# ── Render ───────────────────────────────────────────────────────────────────

def test_kenburns_supersampled_and_anchored_top_third():
    from media.tasks import render
    kb = render.kenburns_filter(1.05, 70, 1080, 1920)
    assert kb.startswith("scale=1620:2880:flags=lanczos") and "(ih-ih/zoom)*0.35" in kb
    assert "s=1080x1920" in kb and "min(1+" in kb
    assert render.kenburns_filter(1.0, 70, 1080, 1920) is None
    assert "scale=1620:1620" in render.kenburns_filter(1.05, 10, 1080, 1080)


def test_final_command_layer_order(temp_db):
    from media.tasks import render
    cmd = render.final_command(
        "reframed.mp4", "out.mp4", fonts_rel="../fonts", ass_main="clip.ass", ass_hook=None, keep=None,
        zoom=1.05, duration=60, effects="hue=h=10.0:s=1.000",
        emojis=[{"path": "/c/e.png", "start": 8, "end": 9, "x": 485, "y": 1100, "size": 110}],
        audio={"volume": 1.2, "muted": False}, preset="reels")
    graph = cmd[cmd.index("-filter_complex") + 1]
    order = [graph.index(k) for k in ("zoompan", "hue=h=10", "ass=clip.ass", "[1:v]format=rgba")]
    assert order == sorted(order)
    assert "loudnorm" in graph and graph.index("loudnorm") < graph.index("volume=1.200")
    assert cmd[cmd.index("-maxrate") + 1] == "12M"
    assert "-loop" in cmd and cmd.index("-loop") < cmd.index("/c/e.png")


def test_clip_words_keeps_manual_highlight():
    from media.tasks import render
    caps = {"words": [{"w": "hola", "start": 10.0, "end": 10.4, "hl": True}, {"w": "", "start": 10.5, "end": 10.6},
                      {"w": "mundo", "start": 20.0, "end": 20.4}]}
    assert render.clip_words(caps, [(19.5, 21.0), (9.5, 11.0)]) == [
        {"w": "mundo", "start": 0.5, "end": 0.9}, {"w": "hola", "start": 2.0, "end": 2.4, "hl": True}]


# ── Caché por fuente ─────────────────────────────────────────────────────────

def test_youtube_id_forms():
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1", "youtu.be/dQw4w9WgXcQ",
                "https://youtube.com/shorts/dQw4w9WgXcQ", "https://m.youtube.com/live/dQw4w9WgXcQ?x=1"):
        assert source_cache.youtube_id(url) == "dQw4w9WgXcQ"
    assert source_cache.youtube_id("https://vimeo.com/123") is None


def test_source_cache_roundtrip_and_fingerprint(temp_db, tmp_path):
    f = tmp_path / "v.bin"
    f.write_bytes(b"a" * 10_000)
    fp = source_cache.file_fingerprint(f)
    f.write_bytes(b"a" * 9_999 + b"b")
    assert source_cache.file_fingerprint(f) != fp
    source_cache.save("yt-abc", "transcript.json", {"words": [1]})
    assert source_cache.load("yt-abc", "transcript.json") == {"words": [1]}
    assert source_cache.load(None, "x.json") is None
    assert source_cache.signature({"a": 1}) != source_cache.signature({"a": 2})
    folder = tmp_path / "p"
    folder.mkdir()
    assert source_cache.project_key({"sourceType": "youtube", "sourceUrl": "youtu.be/dQw4w9WgXcQ"}, folder) \
        == "yt-dQw4w9WgXcQ"
    source_cache.remember_key(folder, "up-123")
    assert source_cache.project_key({"sourceType": "upload"}, folder) == "up-123"


def test_find_sibling_source_links_video(temp_db):
    root = settings().projects_dir
    ids = []
    for _ in range(2):
        pid = db.new_id()
        ids.append(pid)
        with db.connect() as conn:
            conn.execute('INSERT INTO "Project" (id, sourceType, sourceUrl, folder, status, createdAt, updatedAt) '
                         'VALUES (?,?,?,?,?,?,?)', [pid, "youtube", "https://youtu.be/dQw4w9WgXcQ", "x", "READY",
                                                    db.now_iso(), db.now_iso()])
        (root / pid).mkdir(parents=True, exist_ok=True)
    for name in source_cache.SOURCE_FILES:
        (root / ids[0] / name).write_text(name)
    sib = source_cache.find_sibling_source(db.get_project(ids[1]))
    assert sib == root / ids[0]
    source_cache.reuse_source(sib, root / ids[1])
    assert (root / ids[1] / "source.mp4").read_text() == "source.mp4"


# ── Línea de tiempo ──────────────────────────────────────────────────────────

def test_timeline_range_and_peaks(tmp_path):
    a, b, n, interval = timeline_assets.plan_range(12.3, 88.8, 80.0)
    assert (a, b) == (10, 80) and 6 <= n <= timeline_assets.MAX_THUMBS and interval == pytest.approx((b - a) / n)
    wav = tmp_path / "a.wav"
    sr = 16000
    y = np.zeros(sr * 4, dtype=np.int16)
    y[sr * 2:sr * 3] = 20000
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(y.tobytes())
    p = timeline_assets.peaks(wav, 0, 4, count=8)
    assert len(p) == 8 and p[4] == 1.0 and p[0] == 0.0


# ── Fuentes ──────────────────────────────────────────────────────────────────

def test_fonts_upload_list_delete(temp_db):
    from media.config import FONTS_DIR
    listed = {f["name"] for f in fonts.list_fonts()}
    assert {"Montserrat ExtraBold", "Anton"} <= listed
    entry = fonts.add_font("Mi Fuente!.ttf", (FONTS_DIR / "Anton-Regular.ttf").read_bytes())
    assert entry["file"] == "user-Mi-Fuente.ttf" and entry["name"] == "Anton" and not entry["builtin"]
    with pytest.raises(fonts.FontError):
        fonts.add_font("x.ttf", b"hola" * 500)
    with pytest.raises(fonts.FontError):
        fonts.delete_font("Anton-Regular.ttf")  # las incluidas no se borran
    fonts.delete_font("user-Mi-Fuente.ttf")
    assert "user-Mi-Fuente.ttf" not in {f["file"] for f in fonts.list_fonts()}


# ── Cancelación ──────────────────────────────────────────────────────────────

def test_cancel_queued_render_restores_status(temp_db):
    from media.services import cancel
    from media.worker import Worker, cancel_render
    pid = db.new_id()
    with db.connect() as conn:
        conn.execute('INSERT INTO "Project" (id, sourceType, folder, status, createdAt, updatedAt) '
                     'VALUES (?,?,?,?,?,?)', [pid, "youtube", "x", "READY", db.now_iso(), db.now_iso()])
    cid = db.insert_clip(pid, {"startSec": 0, "endSec": 60, "score": 50, "reason": "", "hook": "",
                               "title": "", "description": "", "hashtags": ""})
    db.update_clip(cid, renderStatus="QUEUED")
    db.enqueue_job("render", cid)
    assert cancel_render(Worker(), cid) == {"status": "NONE"}
    assert not db.has_pending_job("render", cid)
    w = Worker()
    w.current = {"type": "render", "targetId": cid}
    assert cancel_render(w, cid) == {"status": "CANCELLING"} and cancel.requested(cancel.render_key(cid))
    cancel.clear(cancel.render_key(cid))
