"""Cortes de cámara y tamaño del video para el reencuadre."""


def detect_scenes(video_path):
    """([(inicio, fin), ...], fps): escenas por cambio de contenido (PySceneDetect)."""
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(video_path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video=video)
    return manager.get_scene_list(), video.frame_rate


def get_video_resolution(video_path):
    """(ancho, alto) en píxeles; IOError si OpenCV no abre el archivo."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise IOError(f"No se pudo abrir el video: {video_path}")
        return (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        capture.release()
