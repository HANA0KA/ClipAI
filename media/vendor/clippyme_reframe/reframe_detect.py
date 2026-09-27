"""Detectores del reencuadre: rostros (MediaPipe), boca (FaceMesh) y, opcional,
personas (YOLOv8).

Adaptado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/reframe_detect.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
Cambios: YOLOv8 (ultralytics, AGPL-3.0) deja de ser obligatorio: solo se carga
con REFRAME_PERSON_DETECTOR=yolo; por defecto `detect_person_yolo` devuelve
None y el reencuadre usa solo MediaPipe. Sin selección de dispositivo CUDA.
Requiere mediapipe 0.10.21 (la API `mp.solutions`).
"""
import os
import threading

import cv2
import mediapipe as mp

_lock = threading.Lock()
_yolo_model = None
_yolo_failed = False
_face_detection = None
_face_mesh = None

_MOUTH_TOP = 13
_MOUTH_BOTTOM = 14
_MOUTH_LEFT = 78
_MOUTH_RIGHT = 308


def person_detector_enabled() -> bool:
    return (os.getenv("REFRAME_PERSON_DETECTOR") or "none").strip().lower() == "yolo"


def _get_yolo_model():
    """YOLOv8n perezoso; None si no está habilitado o no está instalado."""
    global _yolo_model, _yolo_failed
    if not person_detector_enabled() or _yolo_failed:
        return None
    with _lock:
        if _yolo_model is None:
            try:
                from ultralytics import YOLO  # AGPL-3.0, opcional
                _yolo_model = YOLO("yolov8n.pt")
            except Exception:
                _yolo_failed = True
                return None
    return _yolo_model


def _get_face_detection():
    global _face_detection
    with _lock:
        if _face_detection is None:
            _face_detection = mp.solutions.face_detection.FaceDetection(
                model_selection=1, min_detection_confidence=0.5)
    return _face_detection


def _get_face_mesh():
    global _face_mesh
    with _lock:
        if _face_mesh is None:
            _face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False, max_num_faces=1, refine_landmarks=False,
                min_detection_confidence=0.5, min_tracking_confidence=0.5)
    return _face_mesh


def compute_mouth_aspect_ratio(frame_bgr, face_box):
    """Apertura vertical / ancho de la boca (MAR) o None. Importa su varianza
    en el tiempo: una boca quieta varía poco, una que habla oscila."""
    x, y, w, h = face_box
    H, W = frame_bgr.shape[:2]
    pad = int(max(w, h) * 0.2)
    x1, y1 = max(0, int(x - pad)), max(0, int(y - pad))
    x2, y2 = min(W, int(x + w + pad)), min(H, int(y + h + pad))
    if x2 - x1 < 30 or y2 - y1 < 30:
        return None
    roi = frame_bgr[y1:y2, x1:x2]
    rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    rgb.flags.writeable = False
    res = _get_face_mesh().process(rgb)
    if not res.multi_face_landmarks:
        return None
    lm = res.multi_face_landmarks[0].landmark
    rh, rw = roi.shape[:2]
    top = (lm[_MOUTH_TOP].x * rw, lm[_MOUTH_TOP].y * rh)
    bot = (lm[_MOUTH_BOTTOM].x * rw, lm[_MOUTH_BOTTOM].y * rh)
    left = (lm[_MOUTH_LEFT].x * rw, lm[_MOUTH_LEFT].y * rh)
    right = (lm[_MOUTH_RIGHT].x * rw, lm[_MOUTH_RIGHT].y * rh)
    mouth_h = ((top[0] - bot[0]) ** 2 + (top[1] - bot[1]) ** 2) ** 0.5
    mouth_w = ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5
    if mouth_w < 1:
        return None
    return mouth_h / mouth_w


def detect_face_candidates(frame):
    """Todos los rostros del cuadro: [{'box': [x, y, w, h], 'score': área}]."""
    height, width = frame.shape[:2]
    results = _get_face_detection().process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not results.detections:
        return []
    out = []
    for det in results.detections:
        bb = det.location_data.relative_bounding_box
        x, y = int(bb.xmin * width), int(bb.ymin * height)
        w, h = int(bb.width * width), int(bb.height * height)
        if w > 0 and h > 0:
            out.append({'box': [x, y, w, h], 'score': w * h})
    return out


def detect_person_yolo(frame):
    """Respaldo: la persona más grande con YOLO (solo si está habilitado)."""
    model = _get_yolo_model()
    if model is None:
        return None
    best_box, max_area = None, 0
    for result in model(frame, verbose=False, classes=[0]):
        for box in result.boxes:
            x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
            area = (x2 - x1) * (y2 - y1)
            if area > max_area:
                max_area, best_box = area, [x1, y1, x2 - x1, y2 - y1]
    return best_box
