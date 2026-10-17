"""Glosario de correcciones de palabras mal transcritas."""
import json

from media.config import reset_settings
from media.services import glossary


def W(text):
    return [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(text.split())]


def texts(words):
    return [w["w"] for w in words]


def test_single_word_keeps_case_insensitive_match_and_punctuation():
    out, n = glossary.apply(W("dijo Ibay, y luego ¿ibay? no"), [{"from": "ibay", "to": "Ibai"}])
    assert texts(out) == ["dijo", "Ibai,", "y", "luego", "¿Ibai?", "no"] and n == 2


def test_accents_matter():
    out, n = glossary.apply(W("esta está"), [{"from": "esta", "to": "ésta"}])
    assert texts(out) == ["ésta", "está"] and n == 1


def test_phrase_same_length_maps_word_by_word():
    out, n = glossary.apply(W("uso cloud code, siempre"), [{"from": "cloud code", "to": "Claude Code"}])
    assert texts(out) == ["uso", "Claude", "Code,", "siempre"] and n == 1


def test_phrase_different_length_blanks_the_rest_and_keeps_timing():
    words = W("el ibay llanos, hoy")
    out, _ = glossary.apply(words, [{"from": "ibay llanos", "to": "Ibai"}])
    assert texts(out) == ["el", "Ibai,", "", "hoy"]
    assert [w["start"] for w in out] == [w["start"] for w in words]  # tiempos intactos
    one, _ = glossary.apply(W("ibailanos"), [{"from": "ibailanos", "to": "Ibai Llanos"}])
    assert texts(one) == ["Ibai Llanos"]


def test_longest_phrase_wins_and_input_is_not_mutated():
    words = W("cloud code hoy")
    rules = [{"from": "cloud", "to": "X"}, {"from": "cloud code", "to": "Claude Code"}]
    out, _ = glossary.apply(words, rules)
    assert texts(out) == ["Claude", "Code", "hoy"] and texts(words) == ["cloud", "code", "hoy"]


def test_already_correct_is_not_counted():
    out, n = glossary.apply(W("Ibai"), [{"from": "ibai", "to": "Ibai"}])
    assert texts(out) == ["Ibai"] and n == 0


def test_clean_rules_validates_and_dedupes():
    rules = glossary.clean_rules([{"from": " A  b ", "to": "x"}, {"from": "a B", "to": "y"}, {"from": "z", "to": "z"},
                                  {"from": "", "to": "q"}, "basura", {"from": "k" * 90, "to": "m"}])
    assert rules[0] == {"from": "a B", "to": "y"} and len(rules) == 2  # la última manda; 90 → 60 caracteres


def test_load_reads_data_glossary(temp_db):
    (temp_db.parent / "glossary.json").write_text(json.dumps({"rules": [{"from": "ibay", "to": "Ibai"}]}))
    reset_settings()
    assert texts(glossary.apply(W("ibay"))[0]) == ["Ibai"]
    (temp_db.parent / "glossary.json").write_text("no es json")
    assert glossary.load() == []
