# Mapa de reutilización — OpenShorts y ClipPyMe

Código fuente leído en `REFERENCIAS CLIPPING/`:

| Repo | Commit leído | Licencia |
| --- | --- | --- |
| ClipPyMe (`fralapo/clippyme`) | `9959228b1a3a31fd92ee965a7aab677202e7480c` (2026-09-16) | MIT, © 2026 ClippyMe |
| OpenShorts (`mutonby/openshorts`) | `77d3a1143e97b2157272f63bfee232bf7423f784` (2026-09-26) | MIT, © 2024 OpenShorts (salvo `cloud/`, licencia comercial, no usada) |

Criterio: el plan manda. Se copian funciones puras pequeñas a `media/services/`;
el reencuadre de ClipPyMe (≈2.600 líneas repartidas en 6 módulos con muchas
ramas por flags) se vendoriza **recortado** en `media/vendor/clippyme_reframe/`
y solo `media/services/reframe_adapter.py` lo importa.

Leyenda de la columna «Acción»: **copiar** = casi literal; **adaptar** = se toma
la lógica y se recorta o cambia la interfaz; **escribir** = código propio (el
repo sirvió solo de referencia o no aporta nada).

## Piezas del plan

| Pieza del plan | Repo | Archivo y funciones | Dependencias | Acción | Justificación |
| --- | --- | --- | --- | --- | --- |
| 6.4 Estrategia por escena TRACK / WIDE / GENERAL (7 cuadros por escena, movimiento > 12 % → WIDE) | ClipPyMe | `pipeline/reframe.py`: `analyze_scenes_strategy`, `create_general_frame`, `_resize_to_output`, `create_disabled_reframe`, `select_cover_frame` | cv2, numpy, mediapipe | adaptar → `vendor/clippyme_reframe/reframe.py` | Es la lógica central probada. Se quitan los modos `subject/object` (FrameShift), el recorte por saliencia y por pesos de objetos, el bucle *streaming* legacy y los tqdm/prints. |
| 6.4 Cámara quieta por escena (dos pasadas: rastrear → fijar mediana por escena → renderizar) | ClipPyMe | `pipeline/reframe.py`: `_render_global_smooth` (rama `REFRAME_STATIC_AUTO`), `process_video_to_vertical` | cv2, numpy, subprocess ffmpeg | adaptar → `vendor/.../reframe.py`: `track_static_targets` + `render_frames` + `encode_vertical` | Se parte en tres funciones para que el adaptador pueda intercalar el diseño SPLIT por cuadro. Se eliminan los suavizadores savgol/kalman/L2 (no se usan con cámara quieta) y el Ken Burns plegado (va en el pase final). |
| Protecciones: VFR→CFR, `fps` del lector, desfase de `start_time` del audio, cuadros corruptos | ClipPyMe | `pipeline/reframe.py` (bloques VFR y guardia de cuadros), `pipeline/media_probe.py`: `parse_frame_rate`, `is_vfr`, `parse_start_time`, `audio_sync_seek_args`, `reconcile_fps`, `probe_stream_start_time`, `probe_is_variable_frame_rate`; `pipeline/run_ops.py`: `build_vfr_normalization_command` | ffprobe/ffmpeg | copiar → `vendor/clippyme_reframe/media_probe.py` | Protecciones pedidas explícitamente. Se parametriza el binario de ffmpeg/ffprobe (en Mac hace falta `ffmpeg-full` para libass). |
| Cámara virtual y hablante activo | ClipPyMe | `pipeline/reframe_track.py`: `DetectionSmoother`, `SmoothedCameraman` (`update_target`, `crop_box_at`), `SpeakerTracker` | ninguna (puro) | adaptar → `vendor/.../reframe_track.py` | Se quitan los suavizadores `euro`/`spring` y `get_crop_box` (bucle streaming no usado). Se conservan `REFRAME_SPEAKER_SWITCH_MARGIN`, `REFRAME_MIN_FACE_RATIO`, `REFRAME_LOST_HOLD`. |
| Matemática de encuadre | ClipPyMe | `pipeline/reframe_ops.py`: `collapse_scene_targets`, `centroid_span`, `zoom_for_face_height`, `letterbox_plan` | numpy | adaptar → `vendor/.../reframe_ops.py` | Solo las 4 funciones que usa la cámara quieta; fuera OneEuro, savgol, Kalman, L2, PanSmoother, saliencia. |
| Detectores de rostro y boca | ClipPyMe | `pipeline/reframe_detect.py`: `detect_face_candidates`, `compute_mouth_aspect_ratio`, `detect_person_yolo` | mediapipe 0.10.21 (`mp.solutions`), ultralytics opcional | adaptar → `vendor/.../reframe_detect.py` | YOLOv8 (AGPL-3.0) pasa a opcional detrás de `REFRAME_PERSON_DETECTOR=yolo`; por defecto solo MediaPipe. mediapipe se fija a 0.10.21: la 1.0 eliminó `mp.solutions` y su API Tasks aborta en macOS. |
| Detección de escenas | ClipPyMe | `pipeline/scene_detection.py`: `detect_scenes`, `get_video_resolution` | scenedetect, cv2 | copiar → `vendor/.../scene_detection.py` | 30 líneas, sin cambios de lógica. |
| Diseño SPLIT (dos personas apiladas, ≥ 50 % de cuadros con ambos rostros) | OpenShorts | `split_layout.py`: `dedupe_faces`, `_two_largest`, `_centre`, `analyze_scene`, `split_geometry`, constantes `MIN_COEXISTENCE`, `MIN_SEPARATION`, `MIN_FACE_WIDTH`, `MIN_SCENE_SECONDS`, `SPLIT_TIGHTNESS`; `frame_sampler.py`: `read_at` | numpy, cv2 | adaptar → `services/reframe_adapter.py` | El plan pide portarlo al adaptador. En vez de un filtergraph `vstack` por escena se compone por cuadro en numpy dentro del mismo pase de render de ClipPyMe (un solo encode). Se aplica a escenas que ClipPyMe marca WIDE (su veredicto de «varias caras»), como pide la tabla 6.4. |
| Hablante activo en conversaciones (cortar en seco en vez de SPLIT, opcional) | OpenShorts | `active_speaker.py`: `mouth_region`, `audio_envelope`, `normalise_activity`, `attribute_windows`, `hold` | numpy, ffmpeg | adaptar → `services/reframe_adapter.py` (`SPEAKER_CUT=1`) | Normaliza la actividad por persona (luz/contraste) y exige audio para votar. Se calcula dentro del pase de rastreo, sin decodificar dos veces. |
| Tramos por diseño y subtítulos en la unión con `\an5` | OpenShorts | `layout_ranges.py`: `write`, `read`, `normalise`, `split_ranges`, `in_split`; `subtitles.py`: `seam_prefix` dentro de `generate_ass` | ninguna | adaptar → `services/layout_ranges.py` y lógica de unión en `services/ass_builder.py` | El sidecar `<clip>.layout.json` es exactamente lo que pide 6.4. |
| Generador ASS con 3 plantillas, palabra resaltada y gancho con caja | OpenShorts | `subtitles.py` (`generate_ass`, formato de colores ASS) | ninguna | escribir → `services/ass_builder.py` | El suyo está atado a su UI (PlayResY 288, SRT, efectos). El plan pide plantillas JSON, 1080×1920, Montserrat 80 px, `MarginV≈600`, gancho 0–3 s con caja. Solo se adapta la idea del prefijo `\an5` por evento. |
| Bordes palabra → frase → silencio | ClipPyMe | `pipeline/cut_ops.py`: `snap_clip_to_words`, `_is_sentence_final`, `sentence_boundaries`, `snap_clip_to_sentences`, `refine_edges_to_silence`, `compute_neighbor_bounds`; `pipeline/media_probe.py`: `parse_silencedetect`, `detect_silences` | ffmpeg (solo `detect_silences`) | adaptar → `services/cut_ops.py` | Tope de duración a 90 s (plan), palabras con clave `w`, abreviaturas en español. Fuera: predicción de Smart Cut, `SnapEvent`, fades. |
| Lectura tolerante del JSON del LLM | ClipPyMe | `pipeline/gemini_parser.py`: `_extract_json_section`, `_clean_json`, `parse_gemini_response` (niveles 1–5) | json-repair (MIT) | adaptar → `services/json_repair.py` | Se desacopla de su esquema `ViralClipsResponse`; valida con cualquier modelo Pydantic y extrae el primer objeto/array JSON (plan 6.8). |
| Cadena de modelos Gemini y reintentos | ClipPyMe | `pipeline/gemini_request.py`: `is_rate_limit_error`, `backoff_seconds`, `build_model_chain`, `_is_retryable_model_error`, `_is_unavailable_model_error`, `generate_with_model_fallback` | google-genai | adaptar → `services/llm.py` | Se añade salida estructurada (`response_schema`) y el proveedor compatible con OpenAI (Ollama). Cadena desde `GEMINI_FALLBACK_MODELS`. |
| TextTiling léxico sin IA | ClipPyMe (portado de ClipsAI) | `pipeline/texttiling_ops.py`: `tokenize`, `gap_scores`, `smooth_scores`, `depth_scores`, `identify_boundaries`, `segment_indices` | numpy | copiar → `services/texttiling_ops.py` | Respaldo cuando no hay embeddings. Se añaden stopwords en español. `find_topic_clips` no se usa: los candidatos los genera el algoritmo del plan. |
| TextTiling con embeddings, candidatos 30–90 s, señales, puntaje, NMS | — | — | sentence-transformers, numpy | escribir → `services/segmentation.py`, `services/candidates.py`, `services/scoring.py` | Algoritmo propio del plan (6.3); los repos eligen momentos con una sola llamada al LLM. |
| Revisión de calidad del render | ClipPyMe | `pipeline/media_qa.py`: `probe_media`, `inspect_signal`; `domain/clip_qa.py`: `evaluate_clip_qa` | ffprobe/ffmpeg | adaptar → `services/media_qa.py` | Se unen en un módulo, binarios parametrizables, se añade la medida de loudness integrada (−14 LUFS). |
| Descarga H.264 y clasificación de errores | ClipPyMe | `pipeline/download.py`: `_FORMAT_LADDER`, `classify_download_error` | yt-dlp | adaptar → `tasks/download.py` | Formato del plan (`bv*[vcodec^=avc1][height<=1080]+ba/b`) con la escalera de ClipPyMe como respaldo; errores «video privado/no disponible» no se reintentan. Si aun así llega AV1/VP9 se transcodifica a H.264 una vez. |
| Ajustes x264 compartidos | ClipPyMe | `domain/encode.py`: `x264_video_args` | ninguna | adaptar → `services/ffmpeg.py` | Variables `X264_CRF`/`X264_PRESET` con los nombres del plan; soporte `h264_videotoolbox`/`h264_nvenc`. |
| Escritura atómica, puntos de control, reintentos acotados, revisión previa | ClipPyMe | `domain/runtime_state.py`, `domain/job_artifacts.py`, `pipeline/orchestrator.py`, `pipeline/preflight.py` | — | escribir → `services/atomic.py`, `worker.py`, `tasks/preflight.py` | Sus versiones dependen de su journal/subprocesos/Docker. Se reescribe la idea (tmp + `os.replace`, fsync, 3 intentos con espera creciente, errores de validación sin reintento) sobre la cola SQLite del plan. |
| Portada automática del clip | ClipPyMe | `pipeline/reframe.py`: `select_cover_frame` | cv2, mediapipe | adaptar → `vendor/.../reframe.py`, expuesto por el adaptador | Nitidez + exposición + rostro. |
| Zoom lento 1,00→1,05 (Ken Burns) | ClipPyMe | `pipeline/reframe.py` (`zoom_vf_args`) | ffmpeg `zoompan` | adaptar → `tasks/render.py` | Se aplica en el pase final (mismo encode que subtítulos y audio). |
| Corte inteligente de silencios | ClipPyMe | `domain/smartcut*.py` (auto-editor + timeline v3) | auto-editor | escribir → `services/smartcut.py` | Su versión depende de un binario descargado en Docker. Se reescribe con `silencedetect` + `select/aselect` de ffmpeg en la misma pasada, después de quemar subtítulos (orden del plan). |
| Publicación | — | — | httpx | escribir → `services/publisher.py` | Interfaz común (`publish(clip, title, description, hashtags, when)`) con proveedores: kit manual, Upload-Post (API pública) y borrador de TikTok (API oficial). Sus publicadores (Zernio/Upload-Post) no se reutilizan (regla 3). |
| Descarga + subtítulos json3/VTT, transcripción Whisper, cola SQLite, API, interfaz | — | — | — | escribir | El plan difiere de ambos repos (ellos transcriben todo con Deepgram/ElevenLabs y tienen su propia API/UI). |

## Lo que NO se reutiliza (regla 3)

| Qué | Repo | Motivo |
| --- | --- | --- |
| `dashboard/` (React 18 + Vite) | ambos | La interfaz es Next.js. |
| `api/app.py`, `app.py`, `main.py` (FastAPI y CLI) | ambos | La API propia llama directo a las funciones. |
| `integrations/social_publisher.py` (Zernio), `s3_uploader.py`, Upload-Post de OpenShorts | ambos | Publicadores de terceros y nube. |
| `cloud/`, `requirements-billing.txt` | OpenShorts | Licencia comercial y cobros. |
| `mcp_server.py`, `mcp_stdio.py`, `mcp_ui.py` | OpenShorts | MCP fuera de alcance. |
| `translate.py`, doblaje, `saasshorts.py` (actores IA), `remotion/`, `render-service/` | OpenShorts | Fuera de alcance. |
| `deepgram_transcribe.py`, `elevenlabs_transcribe.py`, `transcribe_backends.py` | ambos | El plan usa subtítulos de YouTube + Whisper local. |
| `live_monitor.py`, Kick/Twitch/RSS | ClipPyMe | Fuera de alcance. |
| Dockerfiles y `docker-compose*.yml` | ambos | Docker no es obligatorio; todo corre en el host. |
| `reframe_v2.py`, `panel_layout.py`, `screencast_layout.py`, `camera_inset.py` | OpenShorts | Se usa el reencuadre de ClipPyMe; SCREENCAST es opcional en el plan y no se implementa. |

## Dependencias con licencia no MIT

| Dependencia | Licencia | Uso |
| --- | --- | --- |
| ultralytics (YOLOv8) | AGPL-3.0 | **No instalada por defecto.** Solo con `REFRAME_PERSON_DETECTOR=yolo` + `pip install ultralytics`, como respaldo de detección de personas cuando no hay rostro. Sin ella el reencuadre usa solo MediaPipe. |
| mediapipe | Apache-2.0 | Detección de rostros y FaceMesh. |
| faster-whisper / CTranslate2 | MIT | Transcripción. |
| sentence-transformers / modelo MiniLM | Apache-2.0 | Embeddings de TextTiling. |
| PySceneDetect | BSD-3-Clause | Cortes de cámara. |
| yt-dlp | Unlicense | Descarga. |
| FFmpeg (`ffmpeg-full` de Homebrew) | GPL-3.0 (binario externo) | Se invoca como programa, no se enlaza. |
| Fuentes Montserrat y Anton | SIL OFL 1.1 | Copiadas de OpenShorts `fonts/` con su licencia. |
