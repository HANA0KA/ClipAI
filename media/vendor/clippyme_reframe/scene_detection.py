"""Detección de escenas + resolución del video.

Copiado de ClipPyMe — https://github.com/fralapo/clippyme
Ruta original: src/clippyme/pipeline/scene_detection.py
Copyright (c) 2026 ClippyMe — Licencia MIT (ver media/vendor/NOTICE.md).
"""
import cv2
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


def detect_scenes(video_path):
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video=video)
    return scene_manager.get_scene_list(), video.frame_rate


def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height
