"""Funciones puras del adaptador de reencuadre (SPLIT y hablante activo)."""
import numpy as np

from media.services import reframe_adapter as ra


def _face(x, w=200, y=300, h=240):
    return {"box": [x, y, w, h], "score": w * h}


def test_analyze_scene_two_shot_needs_coexistence_and_separation():
    two = [[_face(300), _face(1300)]] * 6 + [[_face(300)]] * 2
    pair = ra.analyze_scene(two, 1920)
    assert pair is not None
    left, right = pair
    assert left[0] == 400 and right[0] == 1400  # centros: izquierda arriba, derecha abajo
    # Plano/contraplano: nunca los dos a la vez → no es SPLIT.
    assert ra.analyze_scene([[_face(300)], [_face(1300)]] * 4, 1920) is None
    # Hombro con hombro (separación < 20 % del ancho) → no es SPLIT.
    assert ra.analyze_scene([[_face(800), _face(1050)]] * 8, 1920) is None
    # Público (3+ rostros grandes) → no es SPLIT.
    crowd = [[_face(100), _face(700), _face(1400)]] * 8
    assert ra.analyze_scene(crowd, 1920) is None


def test_dedupe_faces_drops_duplicate_boxes():
    faces = [_face(300), {"box": [305, 302, 195, 238], "score": 1}, _face(1300)]
    assert len(ra.dedupe_faces(faces)) == 2


def test_split_geometry_fits_source_and_half_frame():
    x, y, w, h, half = ra.split_geometry(1920, 1080, 1080, 1920, (400, 420, 200, 240))
    assert half == 960 and abs(w / h - 1080 / 960) < 0.01
    assert 0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080
    assert x <= 400 <= x + w  # la cara queda dentro
    x2, *_ = ra.split_geometry(1920, 1080, 1080, 1920, (1900, 420, 200, 240))
    assert x2 + w <= 1920  # se ajusta al borde


def test_compose_split_stacks_to_output_size():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:, :960] = 50
    frame[:, 960:] = 200
    top = ra.split_geometry(1920, 1080, 1080, 1920, (400, 540, 200, 240))
    bot = ra.split_geometry(1920, 1080, 1080, 1920, (1500, 540, 200, 240))
    import cv2
    out = ra.compose_split(frame, top, bot, 1080, 1920, lambda img, w, h: cv2.resize(img, (w, h)))
    assert out.shape == (1920, 1080, 3)
    assert out[100, 540, 0] < 128 < out[1800, 540, 0]  # arriba la izquierda, abajo la derecha


def test_active_speaker_pipeline():
    # Persona 0 habla las primeras 6 ventanas, persona 1 las siguientes 6.
    act = [[5.0, 0.5]] * 6 + [[0.5, 5.0]] * 6
    loud = [1.0] * 12
    verdicts = ra.attribute_windows(ra.normalise_activity(act), loud)
    assert verdicts[:6] == [0] * 6 and verdicts[6:] == [1] * 6
    # Ventanas en silencio no votan.
    assert ra.attribute_windows([[5.0, 0.1]], [0.05]) == [None]
    # «hold»: un «sí» aislado no roba el plano.
    held = ra.hold([0, 0, 0, 1, 0, 0, 1, 1, 1, 1])
    assert held == [0, 0, 0, 0, 0, 0, 0, 0, 1, 1]
    assert ra.hold([None, None]) == [None, None]


def test_merge_ranges():
    r = ra._merge_ranges([{"start": 0, "end": 2, "layout": "track"}, {"start": 2, "end": 5, "layout": "track"},
                          {"start": 5, "end": 7, "layout": "split"}])
    assert r == [{"start": 0, "end": 5, "layout": "track"}, {"start": 5, "end": 7, "layout": "split"}]
