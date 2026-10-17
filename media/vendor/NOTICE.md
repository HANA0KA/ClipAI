# Avisos de terceros

ClipAI incluye código de terceros con licencia MIT. Cada archivo copiado o
adaptado lleva una cabecera con el repositorio, la ruta original y el aviso de
copyright, que debe conservarse.

## ClipPyMe

- Repositorio: https://github.com/fralapo/clippyme
- Commit usado: `9959228b1a3a31fd92ee965a7aab677202e7480c` (2026-09-16)
- Licencia: MIT — Copyright (c) 2026 ClippyMe

| Archivo en ClipAI | Origen en ClipPyMe | Tipo |
| --- | --- | --- |
| `media/vendor/reframe/reframe.py` | `src/clippyme/pipeline/reframe.py`, `src/clippyme/pipeline/run_ops.py` | adaptado (recortado) |
| `media/vendor/reframe/reframe_ops.py` | `src/clippyme/pipeline/reframe_ops.py` | adaptado (recortado) |
| `media/vendor/reframe/reframe_detect.py` | `src/clippyme/pipeline/reframe_detect.py` | adaptado |
| `media/services/json_repair.py` | `src/clippyme/pipeline/gemini_parser.py` | adaptado |
| `media/services/llm.py` (cadena de modelos) | `src/clippyme/pipeline/gemini_request.py` | adaptado |
| `media/services/media_qa.py` | `src/clippyme/pipeline/media_qa.py`, `src/clippyme/domain/clip_qa.py` | adaptado |
| `media/services/ffmpeg.py` (`video_args`) | `src/clippyme/domain/encode.py` | adaptado |
| `media/tasks/download.py` (escalera de formatos, errores, cadena de clientes) | `src/clippyme/pipeline/download.py` | adaptado |
| `media/fonts/Anton-Regular.ttf` | `fonts/` (fuente de Google Fonts, SIL OFL 1.1) | copiado |

## OpenShorts

- Repositorio: https://github.com/mutonby/openshorts
- Commit usado: `77d3a1143e97b2157272f63bfee232bf7423f784` (2026-09-26)
- Licencia: MIT — Copyright (c) 2024 OpenShorts 

| Archivo en ClipAI | Origen en OpenShorts | Tipo |
| --- | --- | --- |
| `media/services/reframe_adapter.py` (SPLIT, muestreo, hablante activo) | `split_layout.py`, `frame_sampler.py`, `active_speaker.py` | adaptado |
| `media/services/layout_ranges.py` | `layout_ranges.py` | adaptado |
| `media/fonts/Montserrat-ExtraBold.ttf`, `Montserrat-OFL.txt` | `fonts/` (SIL OFL 1.1) | copiado |
| `media/services/transcript.py` (`merge_continuations`) | `subtitles.py` (`merge_continuation_words`) | adaptado |
| `media/services/llm.py` (bloqueos, precios, costo) | `gemini_worker.py` (`raise_if_blocked`, `_calculate_cost_analysis`), `clip_selection.py` (`MODEL_PRICES`) | adaptado |
| `media/services/punch.py` | `punch_in.py` (curva, constantes) | adaptado |

## Texto de la licencia MIT (aplica a ambos, con su aviso de copyright)

```text
MIT License

Copyright (c) 2026 ClippyMe
Copyright (c) 2024 OpenShorts

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Dependencias con otras licencias

- **ultralytics / YOLOv8 — AGPL-3.0.** No se instala por defecto. Solo se usa si
  defines `REFRAME_PERSON_DETECTOR=yolo` e instalas `ultralytics`; en ese caso,
  distribuir la app obligaría a publicar su código. Sin ella el reencuadre usa
  solo MediaPipe (Apache-2.0).
- **FFmpeg** (binario externo, GPL) se invoca como programa, no se enlaza.
