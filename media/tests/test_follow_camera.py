"""Cámara que sigue a un sujeto que se mueve (FOLLOW) y detecciones confirmadas."""
import numpy as np

from media.vendor.reframe.reframe_ops import _short_excursions, collapse_scene_targets, follow_path

FPS, W, X = 30.0, 600.0, 1920.0


def test_follow_path_still_subject_keeps_camera_still():
    noisy = list(960 + np.random.default_rng(1).normal(0, 15, 300))
    path = follow_path(noisy, fps=FPS, crop_w=W, x_max=X)
    assert max(path) - min(path) < 10


def test_follow_path_walking_subject_stays_in_frame_smoothly():
    walk = [500.0] * 60 + list(np.linspace(500, 1400, 120)) + [1400.0] * 150
    path = follow_path(walk, fps=FPS, crop_w=W, x_max=X)
    assert all(abs(a - b) <= W / 2 for a, b in zip(walk, path))       # nunca se sale del recorte
    assert max(abs(np.diff(path))) <= 0.5 * W / FPS + 1e-6              # tope de velocidad
    assert abs(path[-1] - 1400) < 10                                    # al quedarse quieto, lo recentra
    assert abs(path[30] - 500) < 1                                      # quieto al principio


def test_follow_path_ignores_short_excursions_and_missing_detections():
    xs = [960.0] * 90 + [300.0] * 30 + [960.0] * 90  # 1 s en otra cara (público)
    assert max(abs(v - 960) for v in follow_path(xs, fps=FPS, crop_w=W, x_max=X)) < 5
    valid = [True] * 60 + [False] * 60 + [True] * 90   # sin detección: el objetivo retenido no cuenta
    xs2 = [1000.0] * 60 + [960.0] * 60 + [1000.0] * 90
    assert max(abs(v - 1000) for v in follow_path(xs2, fps=FPS, crop_w=W, x_max=X, valid=valid)) < 5


def test_follow_path_clamped_to_frame():
    assert min(follow_path([0.0] * 50, fps=FPS, crop_w=W, x_max=X)) == W / 2
    assert max(follow_path([X] * 50, fps=FPS, crop_w=W, x_max=X)) == X - W / 2
    assert follow_path([], fps=FPS, crop_w=W, x_max=X) == []


def test_short_excursions_mask():
    x = np.array([0.0] * 10 + [500.0] * 3 + [0.0] * 10 + [500.0] * 20)
    ok = _short_excursions(x, 0.0, 100.0, 5)
    assert not ok[10:13].any() and ok[23:].all() and ok[:10].all()


def _collapse(targets, strategies, seen=None, **kw):
    n = len(targets)
    return collapse_scene_targets(targets, [0] * n, strategies, x_max=1920, y_max=1080, snap_center_dist=0.03,
                                  crop_w_at_zoom1=607, fps=FPS, seen=seen, **kw)


def test_collapse_follow_pans_and_track_upgrades_when_subject_wanders():
    walk = [(float(x), 500.0, 1.0) for x in [500.0] * 60 + list(np.linspace(500, 1400, 120)) + [1400.0] * 90]
    out = _collapse(walk, ["FOLLOW"] * len(walk))
    assert out[0][0] < 700 and out[-1][0] > 1200 and len({o[1] for o in out}) == 1  # panea, altura fija
    static = _collapse(walk, ["TRACK"] * len(walk))
    assert len({o for o in static}) == 1                        # sin follow: cámara quieta como antes
    upgraded = _collapse(walk, ["TRACK"] * len(walk), follow=True)
    assert upgraded[0][0] < 700 and upgraded[-1][0] > 1200      # el recorrido no cabía: pasa a seguir


def test_collapse_without_confirmed_detections_falls_back_to_previous_behaviour():
    targets = [(1320.0, 400.0, 1.2)] * 100
    seen = [False] * 95 + [True] * 5            # 5 % confirmado: no alcanza
    out = _collapse(targets, ["FOLLOW"] * 100, seen=seen)
    assert len({o for o in out}) == 1 and out[0][2] == 1.0     # plano abierto fijo, zoom 1
    wide = [(900.0, 400.0, 1.0)] * 50 + [(1300.0, 400.0, 1.0)] * 50
    assert _collapse(wide, ["WIDE"] * 100, seen=[True] * 50 + [False] * 50) == \
        _collapse(wide, ["WIDE"] * 100)                        # grupos: como siempre


def test_face_confirmer_skips_small_and_group_boxes_and_caches(monkeypatch):
    from media.vendor.reframe import reframe as cr
    calls = []
    monkeypatch.setattr(cr, "has_face_landmarks", lambda frame, box: calls.append(box) or False)
    confirm = cr._FaceConfirmer()
    cand = [{"box": [100, 100, 120, 120]}]
    assert confirm(None, 0, [10, 10, 40, 40], [{"box": [10, 10, 40, 40]}]) is True   # pequeña
    assert confirm(None, 0, [0, 0, 900, 300], cand) is True                          # caja de grupo
    assert confirm(None, 0, [100, 100, 120, 120], cand) is False                     # sin rasgos: objeto
    assert confirm(None, 4, [102, 100, 120, 120], cand) is False and len(calls) == 1  # caché
    assert confirm(None, 20, [102, 100, 120, 120], cand) is False and len(calls) == 2


# ── Gemini: temperatura por modelo e instrucción de sistema ─────────────────

def test_model_temperature_respects_gemini_3_defaults():
    from media.services.llm import DEFAULT_TEMPERATURE, SYSTEM_INSTRUCTION, model_temperature
    assert model_temperature("gemini-2.5-flash", 0.2) == 0.2 and model_temperature("gemini-2.5-flash") == DEFAULT_TEMPERATURE
    for name in ("gemini-3-flash-preview", "gemini-3.5-flash", "publishers/google/models/gemini-3.6-flash",
                 "gemini-flash-latest"):
        assert model_temperature(name, 0.2) is None
    assert model_temperature("llama3.1:8b", 0.0) == 0.0
    assert "nunca inventas" in SYSTEM_INSTRUCTION and "JSON" in SYSTEM_INSTRUCTION


def test_gemini_config_per_model(monkeypatch):
    """La cadena arma la configuración con la temperatura de cada modelo y la instrucción de sistema."""
    from pydantic import BaseModel

    from media.services import llm as L

    class Item(BaseModel):
        a: int

    seen = []

    class Resp:
        text = '[{"a": 1}]'
        usage_metadata = None
        candidates = []
        prompt_feedback = None

    class Models:
        def generate_content(self, model, contents, config):
            seen.append((model, config.temperature, config.system_instruction))
            if model == "gemini-3-flash-preview":
                raise RuntimeError("404 NOT_FOUND model not found")
            return Resp()

    class Client:
        models = Models()

    inst = L.LLM.__new__(L.LLM)
    inst.provider, inst.models, inst.model_index = "gemini", ["gemini-3-flash-preview", "gemini-2.5-flash"], 0
    inst.last_model, inst.usage, inst.sleep = None, L.new_usage(), lambda s: None
    monkeypatch.setattr(inst, "_gemini_client", lambda model=None: Client())
    monkeypatch.setattr(L, "_UNAVAILABLE", set())
    assert inst.generate_list("p", Item, temperature=0.2)[0].a == 1
    assert seen[0][:2] == ("gemini-3-flash-preview", None) and seen[-1][:2] == ("gemini-2.5-flash", 0.2)
    assert all(s[2] == L.SYSTEM_INSTRUCTION for s in seen)
