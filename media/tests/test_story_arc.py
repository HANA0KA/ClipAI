"""Duración dinámica por historia (60–150 s), gancho en pantalla y hashtags por red."""
import json

import pytest

from media.config import reset_settings, settings
from media.services import ass_builder, cut_ops, hashtags, story_arc
from media.services.transcript import to_sentences


def _talk(sentences, t0=0.0, step=0.5):
    """Palabras de una charla: cada frase termina en punto; pausa de 1,5 s
    entre frases marcadas con «||»."""
    words, t = [], t0
    for sentence in sentences:
        pause = sentence.startswith("||")
        sentence = sentence.lstrip("|")
        if pause:
            t += 1.5
        for w in sentence.split():
            words.append({"w": w, "start": round(t, 3), "end": round(t + step * 0.8, 3)})
            t += step
    return words


def _filler(n, label):
    return [" ".join([label] * 9) + " fin." for _ in range(n)]


# ── Configuración ────────────────────────────────────────────────────────────

def test_clip_limits_default_and_absolute_cap(monkeypatch):
    for k in ("CLIP_MIN_SEC", "CLIP_MAX_SEC"):
        monkeypatch.setenv(k, "")
    reset_settings()
    assert (settings().clip_min_sec, settings().clip_max_sec) == (60.0, 150.0)
    monkeypatch.setenv("CLIP_MAX_SEC", "400")  # 2:30 es el máximo absoluto
    reset_settings()
    assert settings().clip_max_sec == 150.0
    monkeypatch.setenv("CLIP_MIN_SEC", "200")  # mínimo por encima del máximo: se recorta
    reset_settings()
    assert settings().clip_min_sec == 150.0
    reset_settings()


def test_fit_duration_without_target_extends_minimally():
    words = _talk(_filler(40, "palabra"))  # frases de 5 s
    s, e, path = cut_ops.fit_duration(0.0, 40.0, words, lo=60, hi=150)
    assert path == "extend_sentence" and 60 <= e - s < 66  # lo justo para llegar al mínimo, sin relleno


# ── Arco ─────────────────────────────────────────────────────────────────────

def _scene():
    intro = _filler(4, "intro")                       # 0–20 s
    hook = ["¿Sabes por qué nadie te escucha de verdad?"]
    body = _filler(14, "desarrollo")                  # ~70 s
    payoff = ["Por eso escuchar es el mayor regalo que puedes dar."]
    tail = ["||" + s for s in _filler(8, "otro")]    # pausa y otro tema
    words = _talk(intro + hook + body + payoff + tail)
    return words, to_sentences(words)


def test_resolve_arc_uses_quotes_and_story_length():
    words, sents = _scene()
    cand = {"start": 20.0, "end": 85.0}
    plan = story_arc.ArcPlan(id=0, hook_quote="¿Sabes por qué nadie te escucha de verdad?", hook_start=999,
                             payoff_quote="Por eso escuchar es el mayor regalo que puedes dar.", payoff_end=5)
    arc = story_arc.resolve_arc(plan, cand, words, sents, lo=60, hi=150, duration=words[-1]["end"])
    hook_w = next(w for w in words if w["w"] == "¿Sabes")
    end_w = next(w for w in words if w["w"] == "dar.")
    assert arc["start"] == pytest.approx(hook_w["start"]) and arc["end"] == pytest.approx(end_w["end"])
    assert 60 < arc["end"] - arc["start"] < 100 and arc["hook_end"] > arc["start"]


def test_repeated_payoff_quote_follows_model_seconds():
    from media.services.moments import locate_phrase
    words = _talk(["Escucha de verdad."] + _filler(10, "medio") + ["Escucha de verdad."] + _filler(4, "cola"))
    first, second = [w for w in words if w["w"] == "Escucha"]
    assert locate_phrase(words, "Escucha de verdad.", 0, 999)[0] == first["start"]  # sin pista: la primera
    assert locate_phrase(words, "Escucha de verdad.", 0, 999, near=second["start"] + 1)[0] == second["start"]


def test_resolve_arc_rejects_unusable_plans():
    words, sents = _scene()
    cand = {"start": 20.0, "end": 85.0}
    far = story_arc.ArcPlan(id=0, hook_quote="otro otro otro otro otro otro otro otro otro fin.",
                            payoff_quote="Por eso escuchar es el mayor regalo que puedes dar.")
    assert story_arc.resolve_arc(far, cand, words, sents, lo=60, hi=150, duration=words[-1]["end"]) is None
    short = story_arc.ArcPlan(id=0, hook_start=20.0, payoff_end=24.0)  # 4 s: ignoró la duración
    assert story_arc.resolve_arc(short, cand, words, sents, lo=60, hi=150, duration=words[-1]["end"]) is None


def test_resolve_arc_teaser_only_when_inside_and_short():
    words, sents = _scene()
    plan = story_arc.ArcPlan(id=0, hook_quote="¿Sabes por qué nadie te escucha de verdad?",
                             payoff_quote="Por eso escuchar es el mayor regalo que puedes dar.",
                             cold_open=True, teaser_quote="el mayor regalo que puedes dar.")
    arc = story_arc.resolve_arc(plan, {"start": 20.0, "end": 85.0}, words, sents, lo=60, hi=150,
                                duration=words[-1]["end"])
    assert arc["teaser"] and 1.5 <= arc["teaser"][1] - arc["teaser"][0] <= 6.0
    assert arc["teaser"][0] >= arc["start"] + 3


def test_heuristic_end_closes_on_pause_or_topic():
    words, sents = _scene()
    end = story_arc.heuristic_end(20.0, sents, [], lo=60, hi=150, duration=words[-1]["end"])
    assert end == pytest.approx(next(w for w in words if w["w"] == "dar.")["end"])  # sigue una pausa de 1,5 s
    assert story_arc.heuristic_end(20.0, sents, [], lo=60, hi=65, duration=999) is None  # sin cierre antes del tope


def test_arc_prompt_carries_rules_and_zone():
    words, sents = _scene()
    prompt = story_arc.build_arc_prompt([{"start": 20.0, "end": 85.0}], sents, "es", 60, 150, 200)
    for rule in ("GANCHO", "REMATE", "NO rellenes", "150 s", "APERTURA EN FRÍO", "tiktok", "instagram", "youtube"):
        assert rule in prompt
    assert "### id 0" in prompt and "[20.0]" in prompt


def test_arc_plan_coerces_fields():
    p = story_arc.ArcPlan(id=1, hook_start="1:05", payoff_end="", hook_type="Pregunta", tiktok="#a, #b")
    assert p.hook_start == 65 and p.payoff_end is None and p.hook_type == "question" and p.tiktok == ["#a", "#b"]


# ── Análisis: bordes por historia y solapes ──────────────────────────────────

def test_arc_bounds_fallbacks_and_overlaps():
    from media.tasks.analyze import arc_bounds, drop_overlaps
    words, sents = _scene()
    cand = {"start": 20.0, "end": 85.0}
    llm_arc = arc_bounds(cand, story_arc.ArcPlan(
        id=0, hook_quote="¿Sabes por qué nadie te escucha de verdad?",
        payoff_quote="Por eso escuchar es el mayor regalo que puedes dar."), words, sents, [],
        lo=60, hi=150, duration=words[-1]["end"])
    assert llm_arc["source"] == "llm"
    assert arc_bounds(cand, None, words, sents, [], lo=60, hi=150, duration=words[-1]["end"])["source"] == "heuristic"
    assert arc_bounds(cand, None, words, sents, [], lo=60, hi=65, duration=999)["source"] == "candidate"
    clips = [{"startSec": 0, "endSec": 100, "rank": 0}, {"startSec": 60, "endSec": 160, "rank": 1},
             {"startSec": 150, "endSec": 230, "rank": 2}]
    kept = drop_overlaps(clips)
    assert [(c["startSec"], c["rank"]) for c in kept] == [(0, 0), (150, 1)]


# ── Gancho en pantalla ───────────────────────────────────────────────────────

def test_hook_display_seconds_reading_template_and_spoken():
    tpl = ass_builder.load_template("bold-yellow")  # plantilla: 3 s
    assert ass_builder.hook_display_seconds("Nadie te escucha", tpl) == 3.0
    long = "El error de 40 mil dólares que casi todos cometen"  # 10 palabras → 4 s de lectura
    assert ass_builder.hook_display_seconds(long, tpl) == pytest.approx(4.0)
    assert ass_builder.hook_display_seconds("Corto", tpl, spoken=4.6) == 4.6
    assert ass_builder.hook_display_seconds("Corto", tpl, spoken=20) == ass_builder.HOOK_MAX_SECONDS


def test_hook_events_respect_seconds_override():
    tpl = ass_builder.load_template("bold-yellow")
    ev = ass_builder.hook_events("Nadie te escucha", tpl=tpl, seconds=4.5)[0]
    assert "0:00:00.00,0:00:04.50" in ev
    ev = ass_builder.hook_events("Nadie te escucha", tpl=tpl, seconds=4.5, clip_duration=2.0)[0]
    assert "0:00:00.00,0:00:02.00" in ev


def test_spoken_hook_follows_teaser_and_edits():
    from media.tasks.render import _spoken_hook
    clip = {"startSec": 100.0, "signals": json.dumps({"arc": {"hook_seconds": 3.5}})}
    assert _spoken_hook(clip, [(100.0, 170.0)]) == 3.5
    assert _spoken_hook(clip, [(140.0, 143.0), (100.0, 170.0)]) == pytest.approx(6.5)  # con avance delante
    assert _spoken_hook(clip, [(120.0, 170.0)]) is None  # tramos cambiados en el estudio


# ── Hashtags por red ─────────────────────────────────────────────────────────

def test_normalize_tag_forms():
    assert hashtags.normalize_tag("# Inteligencia artificial") == "#InteligenciaArtificial"
    assert hashtags.normalize_tag("#educación") == "#educación"
    assert hashtags.normalize_tag("💰") is None and hashtags.normalize_tag("#2024") is None
    assert hashtags.normalize_tag("#" + "a" * 40) is None


def test_clean_set_limits_filler_and_discovery():
    sets = hashtags.clean_sets({
        "tiktok": ["#fyp", "#parati", "#Finanzas", "#finanzas", "#viral", "#ahorro", "#inversión", "#bolsa", "#x"],
        "instagram": ["reels", "#Finanzas Personales", "#explore", "#ahorro"],
        "youtube": ["#Shorts", "#fyp", "#finanzas", "#dinero", "#ahorro", "#extra"],
    }, "es")
    assert sets["tiktok"] == ["#fyp", "#Finanzas", "#ahorro", "#inversión", "#bolsa"]  # 1 de descubrimiento, sin relleno
    assert sets["instagram"] == ["#reels", "#FinanzasPersonales", "#ahorro"]
    assert sets["youtube"] == ["#Shorts", "#finanzas", "#dinero", "#ahorro"]  # #Shorts primero + 3


def test_heuristic_sets_and_complete():
    text = "El secreto para ahorrar dinero es invertir en bolsa con disciplina y ahorrar dinero cada mes"
    h = hashtags.heuristic_sets(text, None, "es")
    assert h["tiktok"][0] == "#parati" and h["youtube"][0] == "#Shorts" and "#reels" in h["instagram"]
    assert all(len(h[p]) <= hashtags.LIMITS[p][1] + (1 if p == "youtube" else 0) for p in hashtags.PLATFORMS)
    done = hashtags.complete({"tiktok": ["#uno"], "instagram": [], "youtube": ["#Shorts"]}, h)
    assert len(done["tiktok"]) >= 3 and done["tiktok"][0] == "#uno" and done["youtube"][0] == "#Shorts"


def test_hashtag_prompt_rules():
    prompt = hashtags.build_prompt("hola " * 900, "Título", "Gancho", "es")
    assert "tiktok" in prompt and "máximo 5" in prompt and "…" in prompt


# ── Subtítulos de Whisper dentro de un silencio real ─────────────────────────

def _w(text, a, b):
    return {"w": text, "start": a, "end": b}


def test_snap_out_of_silence_moves_payoff_word_back_to_speech():
    from media.services.transcript import snap_out_of_silence
    sil = [(94.45, 94.95), (95.54, 96.57)]  # habla real: «escuchar» en 94.95–95.54
    words = [_w("cuesta,", 94.05, 94.49), _w("escuchar.", 96.11, 96.37), _w("A", 96.6, 96.8)]
    fixed = snap_out_of_silence(words, sil)
    assert (fixed[1]["start"], fixed[1]["end"]) == (94.95, 95.54)
    assert fixed[0] == words[0] and fixed[2] == words[2] and snap_out_of_silence(fixed, sil) == fixed


def test_snap_out_of_silence_leaves_well_placed_words():
    from media.services.transcript import snap_out_of_silence
    sil = [(122.245, 122.756)]
    partial = [_w("todos,", 121.93, 122.07), _w("Y", 122.49, 122.81), _w("nos", 122.81, 122.91)]
    assert snap_out_of_silence(partial, sil) == partial  # apenas pisa el silencio: bien ubicada
    edge = [_w("Y", 126.8, 127.9), _w("también", 128.04, 128.16)]
    assert snap_out_of_silence(edge, [(126.68, 128.0)]) == edge  # primera del rango: no se sabe qué hay antes
    no_room = [_w("a", 10.0, 10.5), _w("b", 10.9, 11.2), _w("c", 11.3, 11.6)]
    assert snap_out_of_silence(no_room, [(10.6, 11.25)]) == no_room  # sin voz libre al lado


def test_snap_out_of_silence_moves_forward_when_speech_follows():
    from media.services.transcript import snap_out_of_silence
    words = [_w("hola", 1.0, 1.4), _w("pero", 1.6, 1.8), _w("mira", 3.0, 3.3)]
    fixed = snap_out_of_silence(words, [(1.45, 2.2)])  # voz libre en 2.2–3.0
    assert (fixed[1]["start"], fixed[1]["end"]) == (2.2, 3.0)


# ── Calidad del gancho ───────────────────────────────────────────────────────

def test_hook_issues_and_score():
    from media.services.moments import hook_issues, hook_score
    first = "A las personas nos encanta que nos escuchen, pero ¿por qué nos encanta?"
    assert "genérico" in hook_issues("¡Esto te sorprenderá!", first)
    assert "corto" in hook_issues("Escucha", first)
    assert "repite la primera frase" in hook_issues("Por qué nos encanta que nos escuchen", first)
    assert hook_issues("El error que arruina tus conversaciones", first) == []
    assert hook_score("El error que arruina tus conversaciones", first) > hook_score("La regla para hablar", first)
    assert hook_score("", first) == 0


def test_pick_hook_keeps_model_choice_unless_defective():
    from media.services.moments import pick_hook
    first = "Hoy vamos a hablar de escuchar."
    assert pick_hook("La regla de oro para comunicarte", ["El error que arruina tus conversaciones"], first) == \
        ("La regla de oro para comunicarte", ["El error que arruina tus conversaciones"])
    best, alts = pick_hook("Esto te sorprenderá", ["El error que arruina tus conversaciones", "Mira esto",
                                                   "«Tú no escuchas: esperas tu turno»"], first)
    assert best == "El error que arruina tus conversaciones" and alts == ["Tú no escuchas: esperas tu turno"]
    assert pick_hook("", [], first) == ("", [])


def test_arc_plan_hook_options_and_prompt():
    plan = story_arc.ArcPlan(id=0, hook_options="Opción uno | Opción dos\nOpción tres")
    assert plan.hook_options == ["Opción uno", "Opción dos", "Opción tres"]
    prompt = story_arc.build_arc_prompt([{"start": 0, "end": 60}], [], "es", 60, 150, 100)
    assert "hook_options" in prompt and "No vas a creer" in prompt and "no reveles el remate" in prompt
