"""Rastreo de rostros y cámara virtual del reencuadre (clases puras, sin cv2).

* ``DetectionSmoother`` promedia las cajas de cada rostro en una ventana corta para que
  el detector no tiemble.
* ``SpeakerTracker`` da identidad estable a los rostros y decide a quién enfocar según
  tamaño y movimiento de la boca, con histéresis para no saltar entre personas.
* ``SmoothedCameraman`` convierte el objetivo (centro + zoom) en el recorte 9:16.
"""
import math
import os
from collections import deque
from dataclasses import dataclass, field

from .reframe_ops import drift_to_center, zoom_for_face_height


def _env_float(name: str, default: float, low: float = float("-inf"), high: float = float("inf")) -> float:
    return max(low, min(high, float(os.getenv(name, default))))


def _center(box) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2, y + h / 2


def box_iou(first, second) -> float:
    """Intersección sobre unión de dos cajas ``(x, y, ancho, alto)``."""
    (ax, ay, aw, ah), (bx, by, bw, bh) = first, second
    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    inter = max(0.0, overlap_w) * max(0.0, overlap_h)
    union = max(0.0, aw * ah) + max(0.0, bw * bh) - inter
    return inter / union if union > 0 else 0.0


_box_iou = box_iou  # nombre que importa reframe.py


def _union_box(faces) -> list:
    lefts = [f["box"][0] for f in faces]
    tops = [f["box"][1] for f in faces]
    rights = [f["box"][0] + f["box"][2] for f in faces]
    bottoms = [f["box"][1] + f["box"][3] for f in faces]
    return [min(lefts), min(tops), max(rights) - min(lefts), max(bottoms) - min(tops)]


# ── Suavizado de detecciones ─────────────────────────────────────────────────

class DetectionSmoother:
    """Promedia las últimas cajas de cada rostro (ventana móvil) para quitar temblor."""

    FORGET_AFTER_FRAMES = 60
    MAX_MATCH_COST = 2.0

    def __init__(self, window_size=5):
        self.window_size = window_size
        self._tracks: dict[int, deque] = {}
        self._last_frame: dict[int, int] = {}

    def reset(self):
        self._tracks.clear()
        self._last_frame.clear()

    def _closest_track(self, box, taken: set):
        """Id de la pista libre más cercana (distancia relativa al tamaño), o None."""
        cx, cy = _center(box)
        best, best_cost = None, self.MAX_MATCH_COST
        for track_id, history in self._tracks.items():
            if track_id in taken or not history:
                continue
            last = history[-1]
            lx, ly = _center(last)
            scale = max(1.0, box[2], box[3], last[2], last[3])
            cost = math.hypot(cx - lx, cy - ly) / scale
            if cost < best_cost:
                best, best_cost = track_id, cost
        return best

    def smooth(self, candidates, frame_number):
        taken: set = set()
        output = []
        for position, cand in enumerate(candidates):
            track_id = self._closest_track(cand["box"], taken)
            if track_id is None:
                track_id = frame_number * 1000 + position
            taken.add(track_id)
            history = self._tracks.setdefault(track_id, deque(maxlen=self.window_size))
            history.append(tuple(cand["box"]))
            self._last_frame[track_id] = frame_number
            averaged = [int(sum(b[i] for b in history) / len(history)) for i in range(4)]
            output.append({**cand, "box": averaged})
        for track_id in [t for t, seen in self._last_frame.items() if frame_number - seen > self.FORGET_AFTER_FRAMES]:
            del self._tracks[track_id]
            del self._last_frame[track_id]
        return output


# ── Cámara virtual ───────────────────────────────────────────────────────────

class SmoothedCameraman:
    """Cámara virtual acotada: guarda el objetivo (centro y zoom) y calcula el recorte."""

    MAX_ZOOM = 1.6
    FACE_OCCUPANCY = 0.4
    GROUP_BOX_RATIO = 1.35  # una caja más ancha que alta es un grupo: abre el plano

    def __init__(self, output_width, output_height, video_width, video_height,
                 *, aspect_ratio: float = 9 / 16):
        self.output_width, self.output_height = output_width, output_height
        self.video_width, self.video_height = video_width, video_height
        self.aspect_ratio = float(aspect_ratio)

        # Recorte más grande que cabe en el video con esa proporción…
        crop_h = video_height
        crop_w = int(crop_h * self.aspect_ratio)
        if crop_w > video_width:
            crop_w = video_width
            crop_h = int(crop_w / self.aspect_ratio)
        self.max_crop_width, self.max_crop_height = crop_w, crop_h
        # …y el más pequeño permitido por el zoom máximo.
        self.min_crop_height = int(crop_h / self.MAX_ZOOM)
        self.min_crop_width = int(self.min_crop_height * self.aspect_ratio)

        self.target_center_x = video_width / 2
        self.target_center_y = video_height / 2
        self.target_zoom = 1.0
        self.frames_since_target = 0
        self.lost_hold_frames = int(os.getenv("REFRAME_LOST_HOLD", "90"))
        self.lost_drift_rate = float(os.getenv("REFRAME_LOST_DRIFT", "0.05"))

    def update_target(self, face_box, is_person_box: bool = False):
        if not face_box:
            return
        self.frames_since_target = 0
        x, y, w, h = face_box
        self.target_center_x = x + w / 2
        if is_person_box:  # cuerpo entero: apunta a la cabeza
            self.target_center_y = y + h * 0.15
            self.target_zoom = 1.0
            return
        self.target_center_y = y + h / 2
        if w > h * self.GROUP_BOX_RATIO:
            self.target_zoom = 1.0
        else:
            self.target_zoom = zoom_for_face_height(
                h, self.max_crop_height, target_occupancy=self.FACE_OCCUPANCY,
                min_zoom=1.0, max_zoom=self.MAX_ZOOM)

    def tick(self):
        """Un cuadro sin objetivo nuevo: pasado ``lost_hold_frames`` el objetivo vuelve
        poco a poco al centro y al plano abierto."""
        self.frames_since_target += 1
        if self.frames_since_target <= self.lost_hold_frames:
            return
        args = (self.frames_since_target, self.lost_hold_frames, self.lost_drift_rate)
        self.target_center_x = drift_to_center(self.target_center_x, self.video_width / 2, *args)
        self.target_center_y = drift_to_center(self.target_center_y, self.video_height / 2, *args)
        if self.target_zoom > 1.0:
            self.target_zoom = max(1.0, self.target_zoom - 0.01)

    def crop_box_at(self, cx: float, cy: float, zoom: float):
        """(x1, y1, x2, y2) del recorte centrado en (cx, cy) con ese zoom, dentro del video."""
        width = max(self.min_crop_width, int(self.max_crop_width / zoom))
        height = max(self.min_crop_height, int(self.max_crop_height / zoom))
        cx = min(max(cx, width / 2), self.video_width - width / 2)
        cy = min(max(cy, height / 2), self.video_height - height / 2)
        return (max(0, int(cx - width / 2)), max(0, int(cy - height / 2)),
                min(self.video_width, int(cx + width / 2)), min(self.video_height, int(cy + height / 2)))


# ── Hablante activo ──────────────────────────────────────────────────────────

@dataclass
class _Face:
    """Un rostro visible en el cuadro actual."""
    id: int
    box: list
    score: float
    mar: float | None = None


@dataclass
class _Identity:
    id: int
    box: list
    last_frame: int


@dataclass
class _Scores:
    """Estado por rostro que sobrevive entre cuadros."""
    speaking: dict = field(default_factory=dict)   # id -> puntaje suavizado de hablante
    mouth: dict = field(default_factory=dict)      # id -> últimas aperturas de boca
    seen: dict = field(default_factory=dict)       # id -> último cuadro visto


class SpeakerTracker:
    """Da identidad estable a los rostros y elige a quién enfocar.

    La identidad combina solapamiento (IoU) y distancia normalizada, así que resiste a dos
    personas que se cruzan. Quien desafía al hablante actual debe superarlo por un margen
    relativo y esperar el enfriamiento. Si dos rostros destacados puntúan parecido y están
    lejos, se devuelve una caja de grupo para mantener a ambos en cuadro.
    """

    MOUTH_WINDOW = 25
    SIZE_WEIGHT = 0.30
    MOUTH_WEIGHT = 1.0
    IDENTITY_TTL = 30        # cuadros que se recuerda un rostro que dejó de verse
    SCORE_FORGET = 60        # cuadros tras los que se olvida su puntaje
    HIDDEN_DECAY = 0.82      # el puntaje de quien no se ve cae así por cuadro
    SMOOTHING = 0.72         # peso del puntaje previo en el promedio exponencial

    def __init__(self, cooldown_frames=30):
        self.switch_cooldown = cooldown_frames
        self.switch_margin = max(1.0, _env_float("REFRAME_SPEAKER_SWITCH_MARGIN", 1.25))
        self.min_face_ratio = _env_float("REFRAME_MIN_FACE_RATIO", 0.10, 0.0, 1.0)
        self.group_enabled = os.getenv("REFRAME_DIALOGUE_GROUP", "1").lower() not in {"0", "false", "no"}
        self.group_score_ratio = _env_float("REFRAME_DIALOGUE_SCORE_RATIO", 0.88, 0.5, 1.0)
        self.group_separation = _env_float("REFRAME_DIALOGUE_SEPARATION", 0.28, 0.05, 0.9)
        self.active_speaker_id = None
        self.last_switch_frame = -1000
        self.locked_counter = 0
        self._next_id = 0
        self._identities: list[_Identity] = []
        self._state = _Scores()

    def reset(self, frame_number=None):
        """Olvida rostros y puntajes (cambio de escena)."""
        self.active_speaker_id = None
        self.locked_counter = 0
        self._identities = []
        self._state = _Scores()
        if frame_number is not None:
            self.last_switch_frame = frame_number - self.switch_cooldown

    # -- identidad ----------------------------------------------------------

    def _identify(self, box, frame_number, frame_width, taken: set) -> int:
        cx, cy = _center(box)
        best_id, best_cost = None, float("inf")
        for known in self._identities:
            if known.id in taken or frame_number - known.last_frame > self.IDENTITY_TTL:
                continue
            kx, ky = _center(known.box)
            scale = max(1.0, box[2], box[3], known.box[2], known.box[3], frame_width * 0.03)
            distance = math.hypot(cx - kx, cy - ky) / scale
            overlap = box_iou(box, known.box)
            cost = distance - 0.75 * overlap
            if cost < best_cost and (overlap >= 0.05 or distance <= 1.8):
                best_id, best_cost = known.id, cost
        if best_id is None:
            best_id, self._next_id = self._next_id, self._next_id + 1
        return best_id

    def _observe(self, detections, frame_number, frame_width) -> list[_Face]:
        """Asigna identidad a los rostros del cuadro, del más grande al más pequeño."""
        faces, taken = [], set()
        for det in sorted(detections, key=lambda d: float(d.get("score") or 0), reverse=True):
            face_id = self._identify(det["box"], frame_number, frame_width, taken)
            taken.add(face_id)
            self._identities = [k for k in self._identities if k.id != face_id]
            self._identities.append(_Identity(face_id, list(det["box"]), frame_number))
            size = float(det.get("score") or det["box"][2] * det["box"][3])
            faces.append(_Face(face_id, det["box"], size, det.get("mar")))
            self._state.seen[face_id] = frame_number
            if det.get("mar") is not None:
                trail = self._state.mouth.setdefault(face_id, [])
                trail.append(float(det["mar"]))
                del trail[:-self.MOUTH_WINDOW]
        return faces

    # -- puntaje ------------------------------------------------------------

    def _mouth_activity(self, face_id) -> float:
        trail = self._state.mouth.get(face_id, [])
        if len(trail) < 5:
            return 0.35  # sin datos suficientes: valor neutro
        mean = sum(trail) / len(trail)
        variance = sum((m - mean) ** 2 for m in trail) / len(trail)
        return min(variance * 200.0, 3.0)

    def _update_scores(self, faces: list[_Face], frame_number, frame_width):
        speaking = self._state.speaking
        visible = {f.id for f in faces}
        for face_id in list(speaking):
            if face_id not in visible:
                speaking[face_id] *= self.HIDDEN_DECAY
            if frame_number - self._state.seen.get(face_id, frame_number) > self.SCORE_FORGET:
                for table in (speaking, self._state.mouth, self._state.seen):
                    table.pop(face_id, None)
        reference_area = max(1.0, frame_width * frame_width * 0.05)
        for face in faces:
            now = self.SIZE_WEIGHT * face.score / reference_area + self.MOUTH_WEIGHT * self._mouth_activity(face.id)
            before = speaking.get(face.id, now)
            speaking[face.id] = before * self.SMOOTHING + now * (1 - self.SMOOTHING)

    def _score(self, face_id) -> float:
        return self._state.speaking.get(face_id, 0.0)

    # -- decisión -----------------------------------------------------------

    def _dialogue_box(self, ranked: list[_Face], frame_width):
        """Caja que reúne a los dos mejores si puntúan parecido y están lejos."""
        if not self.group_enabled or len(ranked) < 2:
            return None
        top, second = ranked[0], ranked[1]
        if self._score(top.id) <= 0:
            return None
        similar = self._score(second.id) / self._score(top.id) >= self.group_score_ratio
        apart = abs(_center(top.box)[0] - _center(second.box)[0]) >= frame_width * self.group_separation
        return _union_box([{"box": top.box}, {"box": second.box}]) if similar and apart else None

    def _switch_to(self, face: _Face, frame_number):
        self.active_speaker_id = face.id
        self.last_switch_frame = frame_number
        self.locked_counter = 0
        return face.box

    def get_target(self, face_candidates, frame_number, width):
        """Caja a enfocar en este cuadro, o None si no hay nadie que seguir."""
        self._identities = [k for k in self._identities if frame_number - k.last_frame <= self.IDENTITY_TTL]
        if not face_candidates:
            return None
        sizes = [max(0.0, float(f.get("score") or f["box"][2] * f["box"][3])) for f in face_candidates]
        floor = max(sizes) * self.min_face_ratio
        detections = [f for f, s in zip(face_candidates, sizes)
                      if float(f.get("score") or f["box"][2] * f["box"][3]) >= floor]

        faces = self._observe(detections, frame_number, width)
        self._update_scores(faces, frame_number, width)
        ranked = sorted(faces, key=lambda f: self._score(f.id), reverse=True)
        challenger = ranked[0]

        group = self._dialogue_box(ranked, width)
        if group is not None:
            return group

        active = next((f for f in faces if f.id == self.active_speaker_id), None)
        if active is None:
            in_cooldown = frame_number - self.last_switch_frame < self.switch_cooldown
            if self.active_speaker_id is not None and in_cooldown:
                return None
            return self._switch_to(challenger, frame_number)
        if challenger.id == self.active_speaker_id:
            self.locked_counter += 1
            return active.box
        cooled = frame_number - self.last_switch_frame >= self.switch_cooldown
        wins = self._score(challenger.id) >= max(0.05, self._score(self.active_speaker_id) * self.switch_margin)
        return self._switch_to(challenger, frame_number) if cooled and wins else active.box
