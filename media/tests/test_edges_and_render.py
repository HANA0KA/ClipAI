"""Bordes, generador ASS, JSON tolerante, corte inteligente, tramos y QA."""
import json
import re

from media.services import ass_builder, cut_ops, layout_ranges, media_qa, smartcut
from media.services.json_repair import parse_json, parse_model_list
from media.services.moments import Proposal


def _words(text, t0=0.0, step=0.5, dur=0.4):
    return [{"w": w, "start": round(t0 + i * step, 3), "end": round(t0 + i * step + dur, 3)}
            for i, w in enumerate(text.split())]


# ── Bordes ───────────────────────────────────────────────────────────────────

def test_snap_to_words_never_mid_word():
    words = _words("uno dos tres cuatro cinco seis")
    s, e = cut_ops.snap_clip_to_words(0.7, 2.2, words)
    assert s == 0.5 - cut_ops.DEFAULT_PRE_PAD  # inicio de «dos»
    assert e == 2.4 + cut_ops.DEFAULT_POST_PAD  # fin de «cinco»


def test_sentence_snap_extends_to_full_sentence():
    words = _words("Esto es el inicio. Aquí empieza la idea que importa. Y aquí termina todo.")
    ws, we = cut_ops.snap_clip_to_words(2.6, 4.4, words)
    s, e, path = cut_ops.snap_clip_to_sentences(2.6, 4.4, words, word_start=ws, word_end=we)
    assert path == "sentence"
    assert abs(s - (2.0 - 0.05)) < 1e-9          # «Aquí»
    assert abs(e - (4.9 + 0.08)) < 1e-9          # fin de «importa.»


def test_sentence_snap_noop_without_punctuation():
    words = _words("sin puntuación alguna en todo el texto de prueba")
    s, e, path = cut_ops.snap_clip_to_sentences(1.0, 3.0, words, word_start=0.95, word_end=3.08)
    assert (s, e, path) == (0.95, 3.08, "word")


def test_is_sentence_final_guards():
    assert cut_ops._is_sentence_final("fin.")
    assert cut_ops._is_sentence_final("¿verdad?")
    assert not cut_ops._is_sentence_final("Sr.")
    assert not cut_ops._is_sentence_final("3.5")
    assert not cut_ops._is_sentence_final("U.S.")


def test_skip_leading_connector():
    words = _words("entonces el secreto es este")
    assert cut_ops.skip_leading_connector(0.0, words) == 0.5 - cut_ops.DEFAULT_PRE_PAD
    assert cut_ops.skip_leading_connector(0.5, words) == 0.5
    two = _words("y entonces el secreto es este")
    assert cut_ops.skip_leading_connector(0.0, two) == 1.0 - cut_ops.DEFAULT_PRE_PAD


def test_parse_silencedetect_and_refine_edges():
    log = ("[silencedetect @ 0x1] silence_start: 9.20\n"
           "[silencedetect @ 0x1] silence_end: 9.95 | silence_duration: 0.75\n"
           "[silencedetect @ 0x1] silence_start: 20.1\n"
           "[silencedetect @ 0x1] silence_end: 21.0 | silence_duration: 0.9\n"
           "[silencedetect @ 0x1] silence_start: 99.0\n")
    sil = cut_ops.parse_silencedetect(log)
    assert sil == [(9.2, 9.95), (20.1, 21.0)]
    s, e, path = cut_ops.refine_edges_to_silence(9.95, 20.08, sil)
    assert path == "silence" and s == 9.95 - cut_ops.DEFAULT_SILENCE_LEAD and e == 20.1 + cut_ops.DEFAULT_SILENCE_TAIL


def test_refine_never_moves_start_into_speech():
    # El silencio más cercano termina DESPUÉS del inicio: moverlo cortaría la primera palabra.
    s, e, path = cut_ops.refine_edges_to_silence(10.0, 40.0, [(10.3, 10.8)])
    assert (s, path) == (10.0, "none")


def test_clean_edges_pipeline():
    words = _words("y entonces la clave de todo es ahorrar y no gastar de más. Luego invertir con calma y "
                   "esperar a que el interés compuesto trabaje por ti.", t0=5.0)
    s, e, path = cut_ops.clean_edges(5.2, 16.4, words, [(3.0, 5.0)])
    assert abs(s - (6.0 - cut_ops.DEFAULT_PRE_PAD)) < 1e-9  # salta «y entonces» y no vuelve al silencio
    assert "connector" in path and "silence_start" not in path


# ── ASS ──────────────────────────────────────────────────────────────────────

def test_ass_colors_and_time():
    assert ass_builder.ass_color("#FFE600") == "&H0000E6FF"
    assert ass_builder.ass_color("#FF0000", 0x80) == "&H800000FF"
    assert ass_builder.ts(3725.456) == "1:02:05.46"


def test_group_words_breaks_on_pause_punctuation_and_size():
    words = _words("hola mundo. esto es una prueba larga")
    words[4]["start"] += 2.0  # pausa antes de «una»
    words[4]["end"] += 2.0
    groups = [[w["w"] for w in g] for g in ass_builder.group_words(words, per_group=3, max_chars=18)]
    assert groups[0] == ["hola", "mundo."]
    assert ["una"] == groups[2][:1] or "una" in groups[2]
    assert all(len(g) <= 3 for g in groups)


def test_build_ass_events_hook_and_seam():
    words = _words("el secreto que nadie te cuenta hoy")
    layout = [{"start": 0.0, "end": 1.0, "layout": "track"}, {"start": 1.0, "end": 10.0, "layout": "split"}]
    ass = ass_builder.build_ass(words, template_id="bold-yellow", hook_text="Nadie te lo dice",
                                clip_duration=10.0, layout=layout)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Caption,Montserrat ExtraBold,84" in ass
    lines = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    hook = [l for l in lines if ",Hook," in l]
    plain = re.sub(r"\{[^}]*\}", "", hook[0]) if hook else ""
    assert len(hook) == 1 and "0:00:00.00,0:00:03.00" in hook[0] and plain.endswith("NADIE TE LO DICE")
    assert "{\\c&H2828D6&}NADIE" in hook[0]  # palabra fuerte en el acento de la plantilla
    caps = [l for l in lines if ",Caption," in l]
    assert len(caps) == len(words)  # un evento por palabra
    assert "{\\an5}" not in caps[0] and "{\\an5}" in caps[-1]  # unión solo en tramos SPLIT
    assert "SECRETO" in caps[1] and "\\c&H00E6FF&" in caps[1]  # palabra activa resaltada


def test_templates_exist_and_escape():
    ids = {t["id"] for t in ass_builder.list_templates()}
    assert {"bold-yellow", "clean-box", "neon-anton"} <= ids
    assert ass_builder.escape_text("a{b}\\c") == "a(b)/c"


# ── JSON tolerante ───────────────────────────────────────────────────────────

def test_parse_json_levels():
    assert parse_json('[{"start": 1, "end": 40}]').parse_path == "strict"
    fenced = 'Claro, aquí está:\n```json\n[{"start": 1, "end": 40,}]\n```\nSaludos'
    r = parse_json(fenced)
    assert r.data == [{"start": 1, "end": 40}] and r.parse_path in ("clean", "strict")
    smart = '{“items”: [{“start”: 5, “end”: 50}]}'
    assert parse_json(smart).data == {"items": [{"start": 5, "end": 50}]}
    broken = '[{"start": 1, "end": 40, "reason": "sin cerrar'
    assert parse_json(broken).data is not None  # json_repair


def test_parse_json_retry_and_model_list():
    calls = []
    r = parse_json("nada de json aquí", retry_fn=lambda err: calls.append(err) or '{"items": []}')
    assert r.parse_path in ("retry", "json_repair") or r.data is not None
    items = parse_model_list({"items": [{"start": 1, "end": 40}, {"start": "x"}]}, Proposal, "items")
    assert len(items) == 1 and items[0].end == 40


# ── Corte inteligente, tramos y QA ───────────────────────────────────────────

def test_keep_segments_removes_long_silences_and_fillers():
    words = [{"w": "hola", "start": 0.0, "end": 0.5}, {"w": "eh", "start": 5.0, "end": 5.3}]
    keep = smartcut.keep_segments(20.0, [(2.0, 4.0), (10.0, 10.3)], words)
    assert keep[0] == (0.0, 2.15)
    assert any(s <= 4.0 and e >= 4.9 for s, e in keep)          # la pausa larga se recorta
    assert not any(s < 5.1 < e for s, e in keep)                  # «eh» fuera
    assert any(s <= 10.0 and e >= 10.3 for s, e in keep)          # pausa corta respetada
    assert "between(t,0.000,2.150)" in smartcut.video_filter(keep)


def test_layout_ranges_roundtrip(tmp_path):
    video = tmp_path / "reframed.mp4"
    layout_ranges.write(video, [(0, 2.5, "TRACK"), (2.5, 9.0, "SPLIT"), (9, 9, "WIDE")])
    ranges = layout_ranges.read(video)
    assert ranges == [{"start": 0.0, "end": 2.5, "layout": "track"},
                      {"start": 2.5, "end": 9.0, "layout": "split"}]
    splits = layout_ranges.split_ranges(ranges)
    assert layout_ranges.in_split(3.0, splits) and not layout_ranges.in_split(1.0, splits)
    assert layout_ranges.shift(ranges, 2.0)[0]["start"] == 2.0
    assert json.loads((tmp_path / "reframed.mp4.layout.json").read_text())["ranges"]


def test_evaluate_clip_qa_critical_vs_warnings():
    ok = media_qa.evaluate_clip_qa(actual_duration=45, expected_duration=45, has_audio=True, has_video=True,
                                   size_bytes=5_000_000, width=1080, height=1920, expected_aspect=9 / 16,
                                   integrated_lufs=-14.3, target_lufs=-14)
    assert ok["ok"] and not ok["critical"]
    bad = media_qa.evaluate_clip_qa(actual_duration=45, expected_duration=45, has_audio=False, has_video=True,
                                    size_bytes=5_000_000, width=1920, height=1080, expected_aspect=9 / 16,
                                    black_ratio=0.6, mean_volume_db=-45)
    assert bad["critical"] and len(bad["issues"]) == 2 and len(bad["warnings"]) == 2


def test_collapse_scene_targets_static_and_keeps_extremes():
    from media.vendor.reframe.reframe_ops import collapse_scene_targets
    # Escena TRACK: el sujeto pasa casi todo el tiempo en x=1100 y al final se va a 1300.
    targets = [(1100.0, 500.0, 1.2)] * 8 + [(1300.0, 500.0, 1.2)] * 2 + [None] * 3
    out = collapse_scene_targets(targets, [0] * 13, ["TRACK"] * 13, x_max=1920, y_max=1080,
                                 snap_center_dist=0.03, crop_w_at_zoom1=607)
    assert len({o for o in out[:10]}) == 1 and out[10] is None  # cámara quieta por escena
    cx, _cy, zoom = out[0]
    w = 607 / zoom
    assert 1300 - 0.4 * w - 1e-6 <= cx <= 1100 + 0.4 * w + 1e-6  # ambos extremos dentro
