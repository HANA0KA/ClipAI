from pathlib import Path

from media.services import transcript

FIX = Path(__file__).parent / "fixtures"


def test_parse_json3_auto_word_timing_and_drops_rollup_and_noise():
    words = transcript.parse_json3(FIX / "auto.json3")
    assert [w["w"] for w in words] == ["hola", "a", "todos", "hoy", "vamos", "a", "aprender"]
    hola, a = words[0], words[1]
    assert hola["start"] == 0.1 and hola["end"] == 0.5
    assert a["start"] == 0.5 and a["end"] == 0.8
    assert words[3]["start"] == 3.0
    assert all(w["end"] > w["start"] for w in words)
    assert all(x["start"] <= y["start"] for x, y in zip(words, words[1:]))


def test_parse_json3_manual_spreads_line_over_event():
    words = transcript.parse_json3(FIX / "manual.json3")
    assert [w["w"] for w in words] == ["Esto", "es", "una", "frase.", "¿Y", "ahora", "qué?"]
    assert words[0]["start"] == 0.0 and words[3]["end"] <= 2.0 + 1e-6
    assert words[4]["start"] == 2.5


def test_parse_vtt_uses_only_inline_timed_lines():
    words = transcript.parse_vtt(FIX / "auto.vtt")
    assert [w["w"] for w in words] == ["hola", "a", "todos", "hoy", "vamos", "a", "aprender"]
    assert words[1]["start"] == 0.5 and words[4]["start"] == 2.3


def test_to_sentences_by_punctuation_and_pause():
    words = [
        {"w": "Hola", "start": 0.0, "end": 0.3}, {"w": "mundo.", "start": 0.35, "end": 0.7},
        {"w": "sin", "start": 0.8, "end": 1.0}, {"w": "puntos", "start": 1.05, "end": 1.4},
        {"w": "pausa", "start": 3.0, "end": 3.3},
    ]
    sents = transcript.to_sentences(words)
    assert [s["text"] for s in sents] == ["Hola mundo.", "sin puntos", "pausa"]
    assert sents[1]["start"] == 0.8 and sents[1]["end"] == 1.4
    assert (sents[1]["w0"], sents[1]["w1"]) == (2, 3)


def test_to_sentences_caps_length():
    words = [{"w": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.2} for i in range(65)]
    sents = transcript.to_sentences(words, max_words=30)
    assert [len(s["text"].split()) for s in sents] == [30, 30, 5]


def test_pick_track_prefers_manual_then_original_auto_never_translation(tmp_path):
    info = {"language": None,
            "subtitles": {"ca": [], "es": []},
            "automatic_captions": {"es": [], "es-es": [], "en-es": []}}
    assert transcript.source_language(info) == "es"
    assert transcript.subtitle_langs(info) == ["es", "es-orig", "es-es"]
    (tmp_path / "source.es-es.json3").write_text("{}")
    (tmp_path / "source.en-es.json3").write_text("{}")
    f, kind, lang = transcript.pick_track(tmp_path, info)
    assert (f.name, kind, lang) == ("source.es-es.json3", "auto", "es")
    (tmp_path / "source.es.json3").write_text("{}")
    f, kind, _ = transcript.pick_track(tmp_path, info)
    assert (f.name, kind) == ("source.es.json3", "manual")


def test_words_from_snippets_and_range():
    words = transcript.words_from_snippets([{"text": "uno dos", "start": 1.0, "duration": 1.0},
                                            {"text": "[Música]", "start": 2.0, "duration": 1.0}])
    assert [w["w"] for w in words] == ["uno", "dos"]
    assert transcript.words_in_range(words, 1.0, 1.4) == [words[0]]
