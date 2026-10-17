"""Huecos en el texto del clip: lo que Whisper se saltó y YouTube sí trae."""
from media.services import gapfill


def W(items):
    return [{"w": w, "start": s, "end": s + 0.3} for w, s in items]


WHISPER = W([("hola", 0.0), ("amigos", 0.5), ("hoy", 10.0), ("vemos", 10.5), ("esto", 11.0)])
YOUTUBE = W([("hola", 0.1), ("amigos", 0.6), ("vamos", 3.0), ("a", 3.5), ("ver", 4.0), ("todo", 5.0),
             ("hoy", 10.1), ("vemos", 10.6), ("esto", 11.1)])


def test_fills_a_gap_with_the_transcript_words_inside_it():
    words, added = gapfill.fill(WHISPER, YOUTUBE, [(0.0, 12.0)])
    assert added == 4 and [w["w"] for w in words] == "hola amigos vamos a ver todo hoy vemos esto".split()
    assert [w["start"] for w in words] == sorted(w["start"] for w in words)


def test_leading_and_trailing_gaps_count_too():
    tail = W([("fin", 15.0), ("del", 15.5), ("clip", 16.0)])
    got = gapfill.candidates(WHISPER, [*YOUTUBE, *tail], [(0.0, 17.0)])
    assert [w["w"] for w in got][-3:] == ["fin", "del", "clip"]
    lead = gapfill.candidates(WHISPER[2:], YOUTUBE, [(0.0, 12.0)])
    assert [w["w"] for w in lead][:2] == ["hola", "amigos"]


def test_no_gap_no_change_and_short_pauses_are_ignored():
    same, added = gapfill.fill(YOUTUBE, YOUTUBE, [(0.0, 12.0)])
    assert added == 0 and same is YOUTUBE
    assert gapfill.candidates(WHISPER, YOUTUBE, [(0.0, 2.0)]) == []  # el hueco cae fuera del tramo


def test_needs_two_words_and_ignores_music_tags():
    one = W([("hola", 0.0), ("adiós", 8.0)])
    assert gapfill.candidates(one, W([("sí", 4.0)]), [(0.0, 9.0)]) == []           # una palabra suelta no basta
    noise = W([("[Música]", 3.0), ("♪", 4.0), ("(aplausos)", 5.0)])
    assert gapfill.candidates(one, noise, [(0.0, 9.0)]) == []
    assert gapfill.is_noise("[Música]") and not gapfill.is_noise("música")


def test_words_near_the_gap_edges_are_not_duplicated():
    edge = W([("amigos", 0.55), ("vamos", 3.0), ("a", 3.5)])  # «amigos» ya está (con otro tiempo)
    got = gapfill.candidates(WHISPER, edge, [(0.0, 12.0)])
    assert [w["w"] for w in got] == ["vamos", "a"]
