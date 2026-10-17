"""Segmentación, candidatos, señales, puntaje y NMS."""
import numpy as np

from media.services import candidates as cm
from media.services import scoring, segmentation, texttiling_ops
from media.services.moments import Judged, locate_phrase, prepend_span, heuristic_kit


def _sents(n, dur=5.0, gap=0.2):
    out, t = [], 0.0
    for i in range(n):
        out.append({"text": f"frase {i}", "start": t, "end": t + dur, "w0": i, "w1": i})
        t += dur + gap
    return out


# ── TextTiling ───────────────────────────────────────────────────────────────

def test_embedding_cuts_finds_topic_change():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=16), rng.normal(size=16)
    e = np.array([a + rng.normal(scale=0.05, size=16) for _ in range(20)]
                 + [b + rng.normal(scale=0.05, size=16) for _ in range(20)])
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    cuts = segmentation.embedding_cuts(e, k=6)
    assert 20 in cuts
    assert all(abs(c - 20) <= 1 for c in cuts)


def test_embedding_cuts_short_input_is_empty():
    assert segmentation.embedding_cuts(np.ones((10, 4)), k=6) == []


def test_lexical_texttiling_splits_two_topics():
    cocina = ["receta pasta tomate cocina horno", "harina huevos cocina receta masa", "tomate albahaca pasta horno"]
    futbol = ["gol partido equipo delantero", "entrenador equipo liga partido", "estadio gol afición liga"]
    sents = [{"text": t} for t in cocina * 4 + futbol * 4]
    cuts = segmentation.lexical_cuts(sents)
    assert cuts and any(10 <= c <= 14 for c in cuts)
    assert texttiling_ops.tokenize("El gol de la liga") == ["gol", "liga"]


def test_chapters_are_mandatory_cuts():
    sents = _sents(10)
    cuts = segmentation.chapter_cuts(sents, [{"start_time": 0}, {"start_time": 26.0}])
    assert cuts == {5}
    assert segmentation.topic_of(7, [3, 6]) == 6 and segmentation.topic_of(1, [3, 6]) == 0


# ── Candidatos ───────────────────────────────────────────────────────────────

def test_windows_respect_duration_and_topics():
    sents = _sents(40)  # 5,2 s por frase
    ws = list(cm.windows(sents, [20], lo=30, hi=90))
    assert ws
    for w in ws:
        assert 30 <= w["end"] - w["start"] <= 90
        assert (w["i"] < 20) == (w["j"] < 20)  # nunca cruzan un corte de tema
        assert w["topic"] in (0, 20)


def test_topic_windows_and_snap():
    sents = _sents(30)
    tw = cm.topic_windows(sents, [10, 20], lo=30, hi=90)
    assert [(w["i"], w["j"]) for w in tw] == [(0, 9), (10, 19), (20, 29)]
    c = cm.snap_to_sentences(12.0, 40.0, sents, [10, 20], lo=30, hi=90)
    assert c is not None and 30 <= c["end"] - c["start"] <= 90 and c["source"] == "llm"


def test_heatmap_peaks_skip_intro_and_space_out():
    dur = 1000.0
    hm = [{"start_time": i * 10.0, "end_time": (i + 1) * 10.0, "value": 0.1} for i in range(100)]
    hm[0]["value"] = 1.0          # pico de arranque (ignorado)
    hm[40]["value"] = 0.9
    hm[41]["value"] = 0.8
    hm[80]["value"] = 0.7
    peaks = cm.heatmap_peaks(hm, dur)
    assert peaks[0] == 405.0 and 805.0 in peaks and 5.0 not in peaks
    assert abs(cm.heat(hm, 400, 420, dur) - 0.85) < 1e-9
    assert cm.heat(None, 0, 10, dur) is None


def test_signals_audio_density_hook():
    z = np.zeros(100)
    z[10:15] = 3.0
    assert cm.audio(z, 10, 20) == 0.5
    words = [{"w": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
             for i, w in enumerate("¿Sabes por qué nadie te cuenta este secreto?".split())]
    assert cm.hook_rule(words, 0.0) > 0.8
    bad = [{"w": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate("y entonces fuimos".split())]
    assert cm.hook_rule(bad, 0.0) < 0.2
    assert cm.density(words, 0, 3.2) > 0.8
    assert cm.density(words, 50, 60) == 0.0


def test_dedupe_keeps_most_informative_source():
    a = {"start": 1.0, "end": 40.0, "source": "window"}
    b = {"start": 1.0, "end": 40.0, "source": "llm"}
    assert cm.dedupe([a, b]) == [b]


# ── Puntaje y selección ──────────────────────────────────────────────────────

def test_llm_and_final_score_formula():
    j = {"hook": 10, "story": 10, "value": 10, "engagement": 10, "reach": 10}
    assert scoring.llm_score(j) == 10
    assert scoring.final_score(j, {"heat": 1.0, "audio": 1.0, "hook": 1.0}) == 100
    j2 = {"hook": 8, "story": 6, "value": 5, "engagement": 4, "reach": 2}
    # S_LLM = 2.4 + 1.5 + 1.0 + 0.6 + 0.2 = 5.7
    assert abs(scoring.llm_score(j2) - 5.7) < 1e-9
    assert scoring.final_score(j2, {"heat": 0.5, "audio": 0.2, "hook": 0.6}) == round(
        100 * (0.55 * 0.57 + 0.20 * 0.5 + 0.15 * 0.2 + 0.10 * 0.6))
    # Sin heatmap su peso se reparte.
    assert scoring.final_score(j2, {"heat": None, "audio": 0.2, "hook": 0.6}) == round(
        100 * (0.65 * 0.57 + 0.22 * 0.2 + 0.13 * 0.6))


def test_nms_overlap_topic_cap_and_top():
    clips = [
        {"start": 0, "end": 60, "score": 90, "topic": 0},
        {"start": 10, "end": 70, "score": 85, "topic": 0},   # solapa 83 % → fuera
        {"start": 50, "end": 110, "score": 80, "topic": 0},  # solapa 10/60 = 17 % → dentro
        {"start": 120, "end": 170, "score": 75, "topic": 0},  # 3.º del tema → fuera
        {"start": 200, "end": 250, "score": 70, "topic": 1},
        {"start": 300, "end": 350, "score": 60, "topic": 2},
    ]
    kept = scoring.nms(clips, max_overlap=0.3, per_topic=2, top=8)
    assert [c["score"] for c in kept] == [90, 80, 70, 60]
    assert len(scoring.nms(clips, top=2)) == 2


def test_prefilter_keeps_llm_and_diversifies():
    sig = {"heat": None, "audio": 0.1, "density": 0.5, "hook": 0.5}
    cands = [{"start": i, "end": i + 40, "source": "window", "signals": dict(sig)} for i in range(0, 20)]
    cands.append({"start": 500, "end": 540, "source": "llm", "signals": dict(sig)})
    pre = scoring.prefilter(cands, top=5)
    assert pre[0]["source"] == "llm"
    assert len(pre) <= 6
    windows = [c for c in pre if c["source"] == "window"]
    assert all(scoring.overlap_ratio(a, b) <= 0.85 for a in windows for b in windows if a is not b)
    many = [{"start": i * 100, "end": i * 100 + 40, "source": "window", "signals": dict(sig)} for i in range(50)]
    assert len(scoring.prefilter(many, top=30)) == 30


def test_heuristic_score_in_range():
    assert 0 <= scoring.heuristic_score({"heat": None, "audio": 0, "density": 0, "hook": 0}) <= 100
    assert scoring.heuristic_score({"heat": 1, "audio": 1, "density": 1, "hook": 1}) == 100


# ── Juez y frase más fuerte ──────────────────────────────────────────────────

def test_judged_coerces_values():
    j = Judged.model_validate({"id": "3", "start": "1:05", "end": 95, "hook": 14, "story": "6", "value": 5.4,
                               "engagement": -2, "reach": None, "hashtags": "fe, #vida"})
    assert (j.id, j.start, j.hook, j.value, j.engagement, j.reach) == (3, 65.0, 10, 5, 0, 0)
    assert j.hashtags == ["#fe", "#vida"]


def test_locate_phrase_and_prepend_span():
    text = "hoy les voy a contar el secreto que nadie te dice sobre el dinero y la vida".split()
    words = [{"w": w, "start": 10 + i * 0.5, "end": 10 + i * 0.5 + 0.4} for i, w in enumerate(text)]
    bl = locate_phrase(words, "el secreto que nadie te dice", 10, 30)
    assert bl == (12.5, 15.4)
    span = prepend_span(words, bl, clip_start=5.0)
    assert span[0] == 12.5 and 2.0 <= span[1] - span[0] <= 4.0
    assert prepend_span(words, bl, clip_start=11.0) is None  # ya está al inicio
    assert locate_phrase(words, "nada que ver con esto", 10, 30) is None


def test_heuristic_kit_has_all_fields():
    kit = heuristic_kit([{"text": "¿Por qué ahorrar 10 euros al mes cambia tu vida?"},
                         {"text": "El ahorro compuesto es la clave del dinero."}])
    assert kit["title"] == kit["hook"] and kit["hook"] and "#shorts" in kit["hashtags"]  # el gancho es el título
