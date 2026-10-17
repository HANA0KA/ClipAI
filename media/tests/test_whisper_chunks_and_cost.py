"""Fragmentos de Whisper, metadatos, descarga,
lectura hacia delante, recorte rápido, bloqueos y costo de IA, reglas del
juez y acercamientos en palabras fuertes."""
import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from media.config import reset_settings
from media.services import db, edit_doc, layout_ranges, punch, source_cache
from media.services import llm as llm_mod
from media.services.transcript import join_number_fragments, merge_continuations


# ── Fragmentos de Whisper ────────────────────────────────────────────────────

def test_merge_continuations_uses_leading_space():
    toks = [{"w": " Son", "start": 0.0, "end": 0.3}, {"w": " 40", "start": 0.3, "end": 0.6},
            {"w": ".000", "start": 0.6, "end": 0.9}, {"w": " YouTube", "start": 1.0, "end": 1.4},
            {"w": "-Kanal.", "start": 1.4, "end": 1.9}, {"w": "  ", "start": 2.0, "end": 2.1}]
    assert [(w["w"], w["start"], w["end"]) for w in merge_continuations(toks)] == [
        ("Son", 0.0, 0.3), ("40.000", 0.3, 0.9), ("YouTube-Kanal.", 1.0, 1.9)]


def test_join_number_fragments_only_glues_digits():
    words = [{"w": "40", "start": 0.3, "end": 0.6}, {"w": ".000", "start": 0.6, "end": 0.9},
             {"w": "y", "start": 1.0, "end": 1.1}, {"w": ".28,", "start": 1.2, "end": 1.4},
             {"w": "90", "start": 2.0, "end": 2.2}, {"w": "%", "start": 2.2, "end": 2.3},
             {"w": "3", "start": 3.0, "end": 3.1}, {"w": ".5", "start": 4.0, "end": 4.2}]  # pausa larga: no
    assert [w["w"] for w in join_number_fragments(words)] == ["40.000", "y", ".28,", "90%", "3", ".5"]


def test_clip_words_repairs_stored_fragments():
    from media.tasks import render
    caps = {"words": [{"w": "son", "start": 10.0, "end": 10.3}, {"w": "40", "start": 10.3, "end": 10.6},
                      {"w": ".000", "start": 10.6, "end": 10.9}]}
    assert [w["w"] for w in render.clip_words(caps, [(9.5, 12.0)])] == ["son", "40.000"]


# ── Metadatos, audio y descarga ──────────────────────────────────────────────

def test_final_command_scrubs_metadata_and_peaks_at_minus_2(temp_db):
    from media.tasks import render
    cmd = render.final_command("reframed.mp4", "out.mp4", fonts_rel="../fonts", ass_main="clip.ass",
                               ass_hook=None, keep=None, zoom=None, duration=30)
    assert cmd[cmd.index("-map_metadata") + 1] == "-1" and "-map_chapters" in cmd
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "TP=-2:" in graph


def test_player_client_chain_is_valid_and_urls_single_video():
    from media.tasks import download
    flat = [c for step in download.PLAYER_CLIENT_CHAIN if step for c in step]
    assert "tv_embedded" not in flat and flat[-2:] == ["default", "mweb"]
    assert source_cache.youtube_id("https://www.youtube.com/watch?list=PL123") is None
    assert source_cache.youtube_id("https://www.youtube.com/@canal") is None


# ── Lectura hacia delante ────────────────────────────────────────────────────

def test_scene_strategy_reads_each_sample_once(monkeypatch):
    from media.vendor.reframe import reframe as cr

    class Cap:
        def isOpened(self): return True
        def get(self, prop): return 1920.0
        def release(self): pass

    monkeypatch.setattr(cr.cv2, "VideoCapture", lambda path: Cap())
    asked = []

    def reader(cap, indices):
        asked.extend(indices)
        for _ in indices:
            yield None  # sin cuadro legible → GENERAL
    assert cr.analyze_scenes_strategy("x.mp4", [(0, 100), (100, 110), (110, 110)], reader=reader) == \
        ["GENERAL", "GENERAL", "GENERAL"]
    assert asked == sorted(asked) and len(asked) == 7 + 3  # una sola pasada, en orden


# ── Recorte rápido ───────────────────────────────────────────────────────────

def test_map_to_base_inside_reorder_and_outside():
    from media.tasks.render import map_to_base
    base = [(100.0, 130.0), (200.0, 240.0)]
    assert map_to_base(base, base) == [(0.0, 30.0), (30.0, 70.0)]
    assert map_to_base(base, [(205.0, 230.0), (110.0, 120.0)]) == [(35.0, 60.0), (10.0, 20.0)]
    assert map_to_base(base, [(99.97, 130.02)]) == [(0.0, 30.0)]  # tolerancia de redondeo
    assert map_to_base(base, [(95.0, 120.0)]) is None             # se sale del base
    assert map_to_base(base, [(125.0, 205.0)]) is None            # cruza dos tramos


def test_layout_remap_follows_the_cut():
    ranges = [{"start": 0, "end": 10, "layout": "track"}, {"start": 10, "end": 30, "layout": "split"},
              {"start": 30, "end": 70, "layout": "wide"}]
    assert layout_ranges.remap(ranges, [(35.0, 60.0), (5.0, 15.0)]) == [
        {"start": 0.0, "end": 25.0, "layout": "wide"}, {"start": 25.0, "end": 30.0, "layout": "track"},
        {"start": 30.0, "end": 35.0, "layout": "split"}]


# ── Bloqueos y costo de IA ───────────────────────────────────────────────────

class Item(BaseModel):
    start: float
    end: float


@pytest.fixture()
def gemini_env(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_MODEL", "VERTEX_PROJECT_ID", "GOOGLE_SERVICE_ACCOUNT_JSON",
              "GOOGLE_SERVICE_ACCOUNT_FILE"):
        monkeypatch.setenv(k, "")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite")
    monkeypatch.setattr(llm_mod, "_UNAVAILABLE", set())
    monkeypatch.setattr(llm_mod, "_GLOBAL_ONLY", set())
    reset_settings()
    yield monkeypatch
    reset_settings()


def _resp(text="", block=None, finish=None, prompt=1000, out=200, thoughts=300):
    return SimpleNamespace(
        text=text,
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish), content=None)] if finish else [],
        usage_metadata=SimpleNamespace(prompt_token_count=prompt, candidates_token_count=out,
                                       thoughts_token_count=thoughts))


def test_block_is_not_retried_and_usage_is_counted(gemini_env):
    calls = []
    llm = llm_mod.LLM(sleep_fn=lambda s: None)

    def generate(model, contents, config):
        calls.append(model)
        return _resp(block=SimpleNamespace(name="PROHIBITED_CONTENT"))
    gemini_env.setattr(llm, "_gemini_client", lambda model=None: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate)))
    with pytest.raises(llm_mod.LLMBlocked):
        llm.generate_list("prompt", Item)
    assert calls == ["gemini-2.5-flash"]  # ni reintento ni siguiente modelo
    u = llm.usage
    assert u["calls"] == 1 and u["prompt_tokens"] == 1000 and u["thinking_tokens"] == 300
    assert u["cost_usd"] == pytest.approx((1000 * 0.30 + (200 + 300) * 2.50) / 1e6) and not u["estimated"]


def test_finish_reason_safety_is_a_block_and_prices_lookup():
    assert llm_mod.blocked_reason(_resp(finish="SAFETY")) == "SAFETY"
    assert llm_mod.blocked_reason(_resp(text="[]", finish="STOP")) is None
    assert llm_mod.model_prices("gemini-2.5-flash-lite") == (0.10, 0.40, False)
    assert llm_mod.model_prices("gemini-9-ultra")[2] is True


def test_judge_bisects_blocked_candidates():
    from media.services.moments import Judged
    from media.tasks.analyze import judge_candidates

    pre = [{"start": i * 70.0, "end": i * 70.0 + 65, "text": f"candidato {i}"} for i in range(6)]
    pre[4]["text"] = "PROHIBIDO"
    sent = []

    class FakeLLM:
        max_prompt_chars = 100_000

        def generate_list(self, prompt, model, **kw):
            ctx = "no disponible" not in prompt
            sent.append(ctx)
            if ctx or "PROHIBIDO" in prompt:
                raise llm_mod.LLMBlocked("bloqueado")
            ids = [int(line.split("|")[0]) for line in prompt.split("CANDIDATOS (id|inicio-fin|texto):")[1].split("\n")
                   if "|" in line]
            return [Judged(id=i, start=0, end=65, hook=5, story=5, value=5, engagement=5, reach=5) for i in ids]

    judged, notes = judge_candidates(FakeLLM(), [{"text": "x", "start": 0, "end": 1}], pre, "es", None, 60, 70)
    assert sorted(judged) == [0, 1, 2, 3, 5] and sent[0] is True
    assert any("sin ella" in n for n in notes) and any("rechazado" in n for n in notes)


def test_add_ai_usage_accumulates(temp_db):
    pid = db.new_id()
    with db.connect() as conn:
        conn.execute('INSERT INTO "Project" (id, sourceType, folder, status, createdAt, updatedAt) '
                     'VALUES (?,?,?,?,?,?)', [pid, "youtube", "x", "READY", db.now_iso(), db.now_iso()])
    db.add_ai_usage(pid, {"calls": 2, "prompt_tokens": 1000, "output_tokens": 100, "thinking_tokens": 50,
                          "cost_usd": 0.01, "estimated": False})
    db.add_ai_usage(pid, {"calls": 1, "prompt_tokens": 10, "output_tokens": 0, "thinking_tokens": 0,
                          "cost_usd": 0.002, "estimated": True})
    db.add_ai_usage(pid, {"calls": 0})
    p = db.get_project(pid)
    assert p["aiTokens"] == 1160 and p["aiCostUsd"] == pytest.approx(0.012) and p["aiCostEstimated"] == 1


def test_judge_prompt_has_new_rules():
    from media.services.moments import build_judge_prompt, build_propose_prompt
    judge = build_judge_prompt([{"text": "hola", "start": 0, "end": 1}], [], "es", None, 10_000)
    for rule in ("PRUEBA DE LOS 2 SEGUNDOS", "CALIBRA", "VARIEDAD", "DE ESTE MOMENTO, NO DEL VIDEO",
                 "nunca cortes el remate"):
        assert rule in judge
    assert "no disponible" in build_judge_prompt([], [], "es", None, 10_000, context=False)
    propose = build_propose_prompt([{"text": "hola", "start": 0, "end": 1}], 300, 5, 60, 70, None, 10_000)
    assert "SE ENTIENDE SOLO" in propose and "nunca cortando el remate" in propose


# ── Acercamientos en palabras fuertes ────────────────────────────────────────

def _words(n, step=0.5):
    return [{"w": "palabra", "start": round(i * step, 3), "end": round(i * step + 0.4, 3)} for i in range(n)]


def test_beats_priority_gap_and_skipped_layouts():
    words = _words(140)  # 70 s
    words[10]["w"] = "nunca"          # 5 s, palabra fuerte (prioridad 2)
    words[12]["w"] = "40.000"         # 6 s, cifra (prioridad 1)
    words[60]["hl"] = True            # 30 s, marcada a mano (prioridad 0)
    words[80]["w"] = "secreto"        # 40 s: a 10 s de la marcada → fuera
    words[120]["w"] = "increíble"     # 60 s: dentro de un tramo SPLIT → fuera
    layout = [{"start": 0, "end": 55, "layout": "track"}, {"start": 55, "end": 70, "layout": "split"}]
    assert punch.beat_times(words, 70.0, layout=layout) == [6.0, 30.0]
    words[2]["w"] = "90%"             # 1 s: antes del margen del gancho → fuera
    assert 1.0 not in punch.beat_times(words, 70.0)


def test_punch_curve_and_filter():
    from media.tasks import render
    assert punch.curve(9.0, [10.0]) == 1.0 and punch.curve(11.0, [10.0]) == pytest.approx(punch.MAX_ZOOM)
    assert punch.curve(12.2, [10.0]) == 1.0
    kb = render.kenburns_filter(None, 30, 1080, 1920, [10.0])
    assert kb and "zoompan=z='1*(1+0.120*(if(between((on/30-10.000),0,0.25)" in kb
    assert render.kenburns_filter(None, 30, 1080, 1920, []) is None
    assert "min(1+" in render.kenburns_filter(1.05, 30, 1080, 1920, [10.0])


def test_edit_doc_punch_defaults_on():
    assert edit_doc.parse(None)["punch"] is True
    assert edit_doc.parse(json.dumps({"punch": False}))["punch"] is False
