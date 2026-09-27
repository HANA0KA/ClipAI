# Herramienta personal de Clipping con IA — Plan de Desarrollo



## 1. Resumen y alcance

Es una herramienta de uso personal llamado ClipAI que corre en tu propia computadora: pegas una URL de YouTube o subes un video, la IA elige los momentos más cautivadores y genera clips verticales 9:16 de 30–90 s con subtítulos animados y texto gancho, listos para subir a YouTube Shorts y TikTok. El costo mensual objetivo es USD 0; solo pagarías centavos por video si eliges un modelo de IA de pago.

**Referencias analizadas**

| Plataforma | Qué tomamos de ella |
| --- | --- |
| [OpusClip](https://www.opus.pro) | Selección de momentos con puntaje, subtítulos dinámicos, reencuadre con IA |
| [WayinVideo](https://wayin.ai) | Detección de highlights y cambios de hablante, reencuadre siguiendo rostros, subtítulos animados |
| [Remakeit](https://remakeit.io) | Flujo simple: pegar URL, obtener clips con subtítulos listos para redes |

**Qué cambia al ser de uso personal**

- **Todo corre en local** (`localhost`): sin hosting, sin login, sin pagos, sin colas en la nube.
- **Descargas desde tu conexión de casa**, que evita la mayoría de bloqueos que YouTube aplica a servidores.
- **Sin base de datos en la nube:** SQLite (un archivo local); Supabase solo si más adelante quieres usar la app desde otro dispositivo.
- **Publicación semiautomática:** la app deja listo el MP4, título, descripción y hashtags; lo subes tú en segundos, o lo envías a borradores de TikTok. Las APIs sin auditar solo publican en privado (ver sección 4).

**Incluido**

- Entrada por URL de YouTube o archivo MP4/MOV.
- Transcripción local con marcas de tiempo por palabra (español e inglés).
- 5–10 clips candidatos con puntaje, razón, gancho y título sugeridos.
- Reencuadre vertical automático siguiendo el rostro del hablante.
- Tres plantillas de subtítulos animados y texto gancho editable.
- Editor básico: ajustar inicio/fin, corregir palabras, cambiar plantilla.
- Exportación MP4 1080×1920 + "kit de publicación" (título, descripción, hashtags para copiar).
- Opcional: envío del clip a borradores de TikTok.

**Fuera de alcance:** cuentas de usuario, pagos, multiusuario, hosting y publicación pública automática.

**Equipo recomendado:** PC con 16 GB de RAM y, si es posible, GPU NVIDIA con 8 GB de VRAM, porque WhisperX con el modelo large-v2 [necesita menos de 8 GB de GPU](https://github.com/m-bain/whisperX). Sin GPU funciona en CPU con un modelo más pequeño, varias veces más lento.

## 2. Arquitectura general

Todo corre en tu computadora: Next.js para la interfaz y un servicio Python local para el procesamiento. Solo salen a internet la descarga del video, la llamada a la IA y, si lo activas, el envío a borradores de TikTok.

&#91;embedded content: arquitectura · 4 capas, 13 componentes\]

Next.js guarda el proyecto en SQLite y le pide al servicio Python que lo procese; todos los archivos viven en una carpeta local.

**Flujo de un proyecto**

1. Pegas la URL en `localhost:3000`; Next.js crea el proyecto en SQLite con estado `QUEUED` y llama a `POST http://localhost:8000/jobs`.
2. FastAPI pone el job en una cola en memoria; un único hilo de trabajo ejecuta `download → transcribe → analyze`.
3. El hilo actualiza estado y progreso en SQLite; la interfaz lo consulta cada 3 segundos.
4. Editas y apruebas un clip; se renderiza en `/data/<proyecto>/clips/`.
5. Descargas el MP4 y copias el título y la descripción, o lo envías a borradores de TikTok.

**Decisiones de arquitectura**

- **Sin Redis ni Celery:** eres un solo usuario procesando un video a la vez; una cola en memoria respaldada en SQLite basta. Al reiniciar, los jobs que estaban `RUNNING` vuelven a `QUEUED`.
- **SQLite en lugar de Supabase:** costo cero, sin configuración y se respalda copiando un archivo. Prisma (Next.js) y `sqlite3` (Python) leen el mismo archivo en modo WAL.
- **Archivos en disco:** la UI los reproduce a través de FastAPI (`StaticFiles`), sin almacenamiento en la nube.
- **Un solo comando para arrancar:** un script `start` levanta Next.js y FastAPI juntos.
- **Render con FFmpeg + ASS:** Remotion es gratis para personas individuales ([licencia](https://www.remotion.dev/docs/pricing)), así que queda como mejora opcional para plantillas más animadas.

## 3. Stack tecnológico

Todas las herramientas son gratuitas y de código abierto, salvo la API de IA, que tiene capa gratuita.

| Capa | Herramienta | Rol en el proyecto | Costo | Documentación |
| --- | --- | --- | --- | --- |
| Interfaz | Next.js (App Router) + React | UI, editor, Route Handlers | Gratis | [nextjs.org/docs](https://nextjs.org/docs) |
| Interfaz | Tailwind CSS + shadcn/ui | Estilos y componentes | Gratis | [tailwindcss.com](https://tailwindcss.com/docs) · [ui.shadcn.com](https://ui.shadcn.com) |
| Interfaz | TanStack Query | Consultar progreso cada 3 s | Gratis | [tanstack.com/query](https://tanstack.com/query/latest) |
| Datos | SQLite + Prisma | Proyectos, clips, jobs en un archivo local | Gratis | [Prisma + SQLite](https://www.prisma.io/docs/orm/overview/databases/sqlite) |
| Datos (opcional) | Supabase | Solo si quieres usar la app desde otro dispositivo | Plan gratuito | [supabase.com/docs](https://supabase.com/docs) |
| API local | FastAPI + Uvicorn | Recibe jobs y sirve archivos | Gratis | [fastapi.tiangolo.com](https://fastapi.tiangolo.com) |
| Descarga | yt-dlp + Deno | Video, metadatos y heatmap | Gratis | [yt-dlp](https://github.com/yt-dlp/yt-dlp) |
| Transcripción | WhisperX (o faster-whisper en CPU) | Texto con tiempos por palabra | Gratis | [WhisperX](https://github.com/m-bain/whisperX) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) |
| Diarización (opcional) | pyannote-audio | Quién habla y cuándo | Gratis | [pyannote-audio](https://github.com/pyannote/pyannote-audio) |
| Visión | MediaPipe Face Detector + OpenCV | Seguir rostros para el 9:16 | Gratis | [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector) · [OpenCV](https://docs.opencv.org) |
| Escenas y audio | PySceneDetect + librosa | Cortes de cámara y picos de energía | Gratis | [scenedetect.com](https://www.scenedetect.com) · [librosa.org](https://librosa.org/doc/latest/) |
| Render | FFmpeg + libass (ASS) | Corte, recorte, subtítulos, encode | Gratis | [ffmpeg.org](https://ffmpeg.org/documentation.html) · [etiquetas ASS](https://aegisub.org/docs/latest/ass_tags/) |
| Render (opcional) | Remotion | Plantillas animadas en React | Gratis para individuos | [remotion.dev/docs](https://www.remotion.dev/docs) |
| IA de selección | Gemini 2.5 Flash (principal) | Puntaje de momentos, gancho y título | Capa gratuita | [Gemini API](https://ai.google.dev/gemini-api/docs) |
| IA alternativa | Ollama con un modelo local | Selección sin internet ni límites | Gratis | [ollama.com](https://ollama.com) |

**Notas sobre el stack**

- **Gemini:** la capa gratuita de Gemini 2.5 Flash ronda los 500 pedidos al día y Google muestra el límite exacto en tu panel de AI Studio ([guía](https://www.apideck.com/blog/how-to-get-your-gemini-api-key)). Con su contexto de 1M tokens puedes enviar la transcripción completa de un video en un solo pedido.
- **Ollama:** evita cualquier costo y límite, pero un modelo local pequeño elige peor los momentos; úsalo como respaldo.
- **WhisperX:** la diarización necesita un token gratuito de Hugging Face y aceptar el acuerdo del modelo de pyannote ([README](https://github.com/m-bain/whisperX)); sin ella el sistema igual funciona siguiendo el rostro más grande.
- **Sin login:** la app escucha solo en `127.0.0.1`, así nadie más en tu red puede usarla.

**Añadidos al reutilizar OpenShorts y ClipPyMe** (ver 6.0)

- **Módulo de reencuadre de ClipPyMe** (submódulo git fijado), con sus dependencias YOLOv8 (ultralytics, licencia AGPL-3.0, válida para uso personal) y MediaPipe FaceMesh.
- **Diseño SPLIT de OpenShorts**, portado al adaptador de reencuadre.
- **[auto-editor](https://github.com/WyattBlue/auto-editor)** para el corte inteligente opcional de silencios y muletillas.
- **Intermediario de publicación opcional** ([Upload-Post](https://docs.upload-post.com/resources/pricing-and-limits) o Publora) para publicar en público sin auditar tu app.

## 4. APIs y publicación

Para uso personal solo necesitas una API key gratuita de Gemini. Publicar por API sin auditoría deja los videos privados, así que la ruta recomendada es que la app deje el clip listo y tú lo subas desde el celular o el navegador.

| Servicio | Para qué | ¿Necesario? | Qué obtener | Límite clave |
| --- | --- | --- | --- | --- |
| [Gemini API](https://ai.google.dev/gemini-api/docs) | Elegir momentos, gancho, título y hashtags | Sí | API key en Google AI Studio | Capa gratuita (unos 500 pedidos al día en 2.5 Flash) |
| Hugging Face | Diarización con pyannote | Opcional | Token de lectura + aceptar el acuerdo del modelo | Ninguno relevante |
| [YouTube Data API](https://developers.google.com/youtube/v3/docs/videos/insert) | Subir Shorts automáticamente | No en la fase 1 | Proyecto en Google Cloud + OAuth tipo escritorio | Sin auditoría, los videos quedan bloqueados como privados |
| [TikTok Upload API](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video) | Enviar el clip a tus borradores de TikTok | Opcional | App en TikTok for Developers con scope `video.upload` | Máximo 5 borradores pendientes en 24 h |

**YouTube: por qué subir a mano**

- Todo video subido con `videos.insert` desde un proyecto no verificado queda en modo privado hasta que el proyecto pasa una auditoría ([documentación](https://developers.google.com/youtube/v3/docs/videos/insert)).
- Ese bloqueo no se puede apelar: YouTube indica volver a subir el video desde su app o sitio, o auditar el proyecto ([ayuda de YouTube](https://support.google.com/youtube/answer/7300965?hl=en)).
- Solución de costo cero: la app exporta el MP4 y un "kit de publicación"; lo subes desde la app de YouTube en el celular o desde YouTube Studio. Un video vertical corto se publica como Short automáticamente.
- Si más adelante quieres automatizar, puedes pedir la [auditoría](https://support.google.com/youtube/contact/yt_api_form) para tu herramienta. Publica tu app OAuth en producción aunque esté sin verificar: en modo prueba Google invalida los refresh tokens a los 7 días, y sin verificar está bien para uso personal ([guía](https://www.nuget.org/packages/grdev.youtube-cli)).

**TikTok: envío a borradores (opcional)**

1. Registrar una app en TikTok for Developers, añadir Login Kit y Content Posting API, y pedir el scope `video.upload`.
2. Autorizar tu propia cuenta una vez y guardar el token en un archivo local cifrado.
3. Llamar a `POST /v2/post/publish/inbox/video/init/` y subir el archivo con `FILE_UPLOAD`.
4. Abrir la notificación en la app de TikTok para terminar de editar y publicar; la [documentación](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video) pide avisar al usuario de este paso. Ahí puedes añadir música y efectos nativos.

Esta ruta evita el límite de Direct Post, donde un cliente sin auditoría [solo publica en SELF\_ONLY y con la cuenta en privado](https://developers.tiktok.com/doc/content-sharing-guidelines/). Si registrar la app te resulta pesado, pasa el MP4 al celular (Google Drive, cable o AirDrop) y súbelo directo: funciona igual.

**Kit de publicación:** en la misma llamada a Gemini se generan título (máximo 100 caracteres, con `#Shorts`), descripción de 2–3 líneas y 3–5 hashtags, con un botón de copiar para cada uno.

**Especificación de salida:** MP4, H.264 + AAC, 1080×1920, 30 fps, 30–90 s.

## 5. Modelo de datos

Tres tablas en un archivo SQLite bastan; los datos pesados (transcripción, trayectoria del recorte) van como archivos JSON en la carpeta del proyecto. No necesitas Supabase.

```prisma
datasource db {
  provider = "sqlite"
  url      = "file:../../data/app.db"
}

model Project {
  id          String   @id @default(cuid())
  sourceType  String   // "youtube" | "upload"
  sourceUrl   String?
  title       String?
  durationSec Int?
  language    String?
  folder      String   // data/projects/<id>/
  status      String   @default("QUEUED")
  progress    Int      @default(0)
  error       String?
  clips       Clip[]
  createdAt   DateTime @default(now())
}

model Clip {
  id           String   @id @default(cuid())
  projectId    String
  project      Project  @relation(fields: [projectId], references: [id], onDelete: Cascade)
  startSec     Float
  endSec       Float
  score        Int
  reason       String
  hook         String
  title        String   // título para redes (con #Shorts)
  description  String
  hashtags     String   // "#a #b #c"
  templateId   String   @default("bold-yellow")
  captionsPath String?  // JSON con palabras editadas
  cropPath     String?  // JSON con trayectoria del recorte
  renderStatus String   @default("NONE") // NONE | QUEUED | RUNNING | DONE | FAILED
  outputPath   String?  // MP4 final
  tiktokDraft  Boolean  @default(false)
  postedAt     DateTime? // lo marcas tú al subirlo
}

model Job {
  id        String   @id @default(cuid())
  type      String   // download | transcribe | analyze | render | tiktok_draft
  targetId  String   // id de Project o Clip
  status    String   @default("QUEUED")
  attempts  Int      @default(0)
  error     String?
  createdAt DateTime @default(now())
}
```

**Estados de un proyecto**

| Estado | Barra de progreso | Qué ves |
| --- | --- | --- |
| `QUEUED` | 0 % | "En cola" |
| `DOWNLOADING` | 0–20 % | Descargando el video |
| `TRANSCRIBING` | 20–60 % | Transcribiendo |
| `ANALYZING` | 60–95 % | Buscando los mejores momentos |
| `READY` | 100 % | Lista de clips con puntaje |
| `FAILED` | — | Mensaje de error y botón de reintentar |

**Estructura de la carpeta de datos**

```text
data/
├─ app.db                      # SQLite
└─ projects/<id>/
   ├─ source.mp4  audio.wav  info.json
   ├─ transcript.json
   └─ clips/<clipId>/ (captions.json, crop.json, clip.ass, final.mp4, thumb.jpg)
```

Para ahorrar disco, un botón "Limpiar" borra `source.mp4` y `audio.wav` de proyectos ya terminados. Si algún día quieres Supabase, basta cambiar el `provider` a `postgresql` y la URL.

## 6. Pipeline técnico detallado

Siete pasos convierten una URL en clips listos para subir; los tres primeros corren solos al crear el proyecto y el render cuando apruebas un clip.

### 6.0 Qué se reutiliza de OpenShorts y ClipPyMe

El backend Python no escribe desde cero la parte más difícil, el encuadre vertical: reutiliza el módulo de [ClipPyMe](https://github.com/fralapo/clippyme) y el diseño de pantalla dividida de [OpenShorts](https://github.com/mutonby/openshorts), ambos con licencia MIT. Lo propio del proyecto se mantiene: subtítulos de YouTube para analizar, puntaje con heatmap y la interfaz en Next.js.

ClipPyMe es un fork de OpenShorts "endurecido y ampliado" y declara ser un proyecto personal y autoalojado, así que encaja con tu caso. OpenShorts, con unas 5.300 estrellas, es la base original y la referencia más probada.

| Pieza | Origen | Por qué reutilizarla | Cómo se integra |
| --- | --- | --- | --- |
| Reencuadre automático por escena (seguir rostro, toma abierta, sin rostros) con cámara quieta y hablante activo | ClipPyMe, `pipeline/reframe*.py` | Ya resuelve fuentes con fotogramas variables, desfase audio/video y cuadros corruptos | Submódulo git + adaptador |
| Diseño de dos personas apiladas con subtítulos en la unión | OpenShorts, `split_layout.py` y `layout_ranges.py` | ClipPyMe resuelve dos personas con una toma abierta; OpenShorts las apila y se ve mejor en vertical | Portar al adaptador |
| Ajuste de bordes palabra → frase → silencio | ClipPyMe, `pipeline/cut_ops.py` | Evita cortar a mitad de palabra o de frase | Copiar funciones puras con atribución |
| Lectura robusta del JSON de Gemini y cadena de modelos de respaldo | ClipPyMe, `gemini_parser.py` y `GEMINI_FALLBACK_MODELS` | Tolera respuestas mal formadas y cuotas agotadas | Copiar funciones puras |
| TextTiling léxico sin IA | ClipPyMe, `texttiling_ops.py` (portado de ClipsAI) | Respaldo gratuito si Gemini falla | Copiar |
| Revisión de calidad del render | ClipPyMe, `media_qa.py` | Detecta cuadros negros, video congelado o audio vacío antes de entregar | Copiar o reimplementar con ffprobe |

**Qué no se reutiliza:** sus frontends en React/Vite (tu interfaz es Next.js), su API FastAPI (tu FastAPI llama directamente a las funciones), su transcripción completa (tú usas subtítulos de YouTube) y su publicador de pago.

**Licencias**

- **ClipPyMe:** MIT, "Copyright (c) 2026 ClippyMe" ([LICENSE](https://github.com/fralapo/clippyme/blob/main/LICENSE)). Se puede copiar y modificar conservando ese aviso en los archivos copiados.
- **OpenShorts:** MIT para el núcleo; solo la carpeta `cloud/` (cobros y servicio alojado) tiene una licencia comercial aparte, y no se necesita ([README](https://github.com/mutonby/openshorts)).
- **YOLOv8 (ultralytics):** la usan ambos para detectar personas y tiene licencia AGPL-3.0. Para uso personal no hay problema; si algún día distribuyes la app, esa licencia obliga a publicar tu código o a cambiar a un detector solo con MediaPipe.

**Integración paso a paso**

1. Añadir ClipPyMe como submódulo fijado a un commit concreto, para que una actualización suya no rompa tu app:

```bash
git submodule add https://github.com/fralapo/clippyme media/vendor/clippyme
cd media/vendor/clippyme && git checkout <commit-probado> && cd -
pip install -e media/vendor/clippyme      # registra el paquete "clippyme" (estructura src/)
```

2. Escribir un adaptador delgado, `media/services/reframe_adapter.py`, que sea la única puerta hacia ClipPyMe. El resto de tu código nunca importa `clippyme` directamente; si el repo cambia, solo se ajusta este archivo.
3. Antes de escribir el adaptador, abrir `src/clippyme/pipeline/reframe.py` para leer la firma real de su función de render y de `reframe_detect.py` para los detectores. Los nombres internos pueden cambiar entre versiones: por eso se fija el commit.
4. Copiar a `media/services/` las funciones puras pequeñas (`cut_ops`, parser JSON, TextTiling) con un comentario de atribución y la licencia MIT, en vez de depender de todo el paquete para ellas.
5. Portar desde OpenShorts la lógica de pantalla dividida (`split_layout.py`) y el archivo de tramos por diseño (`layout_ranges.py`) dentro del adaptador.
6. Guardar en `media/vendor/NOTICE.md` qué se tomó de cada repositorio, de qué commit y con qué licencia.

```python
# media/services/reframe_adapter.py — contrato propio, implementación prestada
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ReframeResult:
    output: Path          # clip 1080x1920
    layout_ranges: list   # [{"start": 0.0, "end": 7.4, "layout": "TRACK"}, ...]

def reframe(source_slice: Path, output: Path, mode: str = "auto") -> ReframeResult:
    """mode: auto | track | split | wide | off.
    Llama al render de ClipPyMe (firma leída en su reframe.py del commit fijado)
    y añade el diseño SPLIT portado de OpenShorts cuando hay dos rostros."""
    ...
```

### 6.1 Descarga (task `download`)

```bash
yt-dlp -f "bv*[vcodec^=avc1][height<=1080]+ba/b" --merge-output-format mp4 \
  --write-info-json --write-subs --write-auto-subs \
  --sub-langs "es.*,en.*" --sub-format json3/vtt/best -o "data/projects/{id}/source.%(ext)s" "$URL"
ffmpeg -i source.mp4 -vn -ac 1 -ar 16000 audio.wav
```

- El `info.json` trae título, duración, capítulos y el campo `heatmap`, una lista de puntos con inicio, fin y un valor normalizado entre 0 y 1 ([issue de yt-dlp](https://github.com/yt-dlp/yt-dlp/issues/3888)); queda guardado en la carpeta del proyecto.
- Instala Deno y actualiza yt-dlp cada semana (`yt-dlp -U`); desde tu conexión de casa rara vez harán falta cookies o proxies.
- Marca `progress = 20` al terminar.

### 6.2 Transcripción: subtítulos de YouTube primero, Whisper solo en los clips

Sí conviene usar la transcripción de YouTube, pero solo para *encontrar* los momentos: llega en segundos, sin GPU, y a la IA le basta aunque tenga errores. Whisper se reserva para los 5–10 clips elegidos (unos 5–10 minutos de audio en vez de una hora), porque ahí los errores sí se ven quemados en pantalla.

| Fuente | Precisión | Puntuación | Tiempos | Costo y tiempo |
| --- | --- | --- | --- | --- |
| Subtítulos escritos por el creador | La mejor (humana) | Sí | Por frase | Segundos |
| Subtítulos automáticos de YouTube | Error mediano de 9,9 % por palabra, con una cola larga de videos malos ([estudio, 264 videos](https://youtube-transcript.ai/blog/youtube-auto-caption-accuracy-study)); 87 % de acierto en podcasts ([prueba](https://mdisbetter.com/blog/youtube-auto-captions-vs-ai-transcription)) | El 20 % de los videos no trae ni un punto | Por palabra (formato json3) | Segundos |
| Whisper large-v3 local | 97 % en los mismos podcasts ([prueba](https://mdisbetter.com/blog/youtube-auto-captions-vs-ai-transcription)) | Buena | Por palabra con WhisperX | Minutos por hora de audio con GPU |

**Orden de obtención**

1. **En la misma descarga de yt-dlp** (paso 6.1) se piden los subtítulos; no hace falta otra llamada.
2. **Manual antes que automático:** el `info.json` separa `subtitles` (escritos por humanos) de `automatic_captions`; se elige el primero que exista en el idioma del video (`info.language`).
3. **Formato json3:** trae cada palabra con su desfase en milisegundos, y los duplicados de "rollup" vienen marcados con `aAppend`, así que se descartan con exactitud ([explicación](https://lobehub.com/mcp/pobibibi-youtube-transcript-mcp)). Si falla, se usa VTT como respaldo.
4. **Token PO:** YouTube exige un token de origen para los subtítulos en el cliente web ([guía de yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)); con Deno y el plugin [bgutil](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) yt-dlp lo genera solo.
5. **Respaldo A — youtube-transcript-api:** útil si yt-dlp no trae subtítulos, pero desde una conexión de casa empezó a bloquear tras unas 30 descargas seguidas ([prueba de septiembre de 2026](https://dev.to/xixisuperman/getting-youtube-transcripts-without-the-data-api-and-why-translate-to-100-languages-is-usually-43m8)). Pide el idioma preferido sin exigirlo.
6. **Respaldo B — Whisper completo:** para archivos subidos, videos sin subtítulos o subtítulos desactivados.
7. **No usar traducciones automáticas de YouTube:** son transcripción de máquina traducida por máquina y hoy suelen fallar.

**Código: descarga con subtítulos y lectura de json3**

```python
import json, subprocess, re
from pathlib import Path

def download(url: str, out: Path):
    subprocess.run([
        "yt-dlp", "-f", "bv*[vcodec^=avc1][height<=1080]+ba/b", "--merge-output-format", "mp4",
        "--write-info-json", "--write-subs", "--write-auto-subs",
        "--sub-langs", "es.*,en.*", "--sub-format", "json3/vtt/best",
        "-o", str(out / "source.%(ext)s"), url,
    ], check=True)

def pick_track(out: Path):
    info = json.loads((out / "source.info.json").read_text(encoding="utf-8"))
    lang = (info.get("language") or "es").split("-")[0]
    for kind, keys in (("manual", info.get("subtitles", {})),
                       ("auto", info.get("automatic_captions", {}))):
        for key in (f"{lang}-orig", lang, *[k for k in keys if k.startswith(lang)]):
            f = out / f"source.{key}.json3"
            if key in keys and f.exists():
                return f, kind, lang
    return None, None, lang          # -> Whisper completo

def parse_json3(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for ev in data.get("events", []):
        if ev.get("aAppend") or "segs" not in ev:
            continue
        t0, dur = ev["tStartMs"], ev.get("dDurationMs", 0)
        segs = [s for s in ev["segs"] if s.get("utf8", "").strip()]
        for i, s in enumerate(segs):
            start = (t0 + s.get("tOffsetMs", 0)) / 1000
            nxt = segs[i + 1].get("tOffsetMs", dur) if i + 1 < len(segs) else dur
            words.append({"w": s["utf8"].strip(), "start": start, "end": (t0 + nxt) / 1000})
    return words

def to_sentences(words, max_gap=0.7, max_words=30):
    """Frases por puntuación o, si no hay, por pausas: los automáticos casi no traen puntos."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["start"] - w["end"] if i + 1 < len(words) else 99
        if re.search(r"[.?!…]$", w["w"]) or gap > max_gap or len(cur) >= max_words:
            out.append({"text": " ".join(x["w"] for x in cur),
                        "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
    return out
```

**Pulido de los clips elegidos (después del 6.3)**

1. Cortar el audio de cada clip con 2 s de margen: `ffmpeg -ss START-2 -to END+2 -i source.mp4 -vn -ac 1 -ar 16000 clip.wav`.
2. Transcribirlo con WhisperX forzando el idioma (`language="es"`); con GPU usa `large-v3`, en CPU `small` con `int8`.
3. Sumar el desfase del corte a cada marca de tiempo y guardar el resultado en `captions.json`: son las palabras que se queman como subtítulos.
4. Opcional: pasar el texto por Gemini solo para corregir nombres propios y puntuación, sin cambiar los tiempos.

Con esto, un video de una hora se analiza en segundos y solo se transcriben con precisión unos minutos, lo que hace la herramienta viable incluso en una PC sin GPU.

### 6.3 Algoritmo de detección de momentos virales

Las apps de referencia no publican su código, pero sí sus criterios. Un sistema de dos etapas los reproduce con herramientas gratuitas: primero se generan candidatos autocontenidos de 30–90 s, y después se puntúan con la misma rúbrica que usan OpusClip y WayinVideo, combinada con señales de audiencia y de audio.

**Qué hacen las referencias**

| Herramienta | Cómo elige y puntúa | Qué tomamos |
| --- | --- | --- |
| [OpusClip](https://help.opus.pro/docs/article/virality-score) | Puntaje de 0 a 99 con cuatro ejes: gancho, flujo, valor y tendencia; en ClipAnything también evalúa si el clip responde al pedido del usuario. Su modelo combina señales visuales, de audio y de sentimiento, y reordena el momento para abrir con fuerza ([sitio](https://www.opus.pro)) | Ejes de la rúbrica, búsqueda por instrucción, gancho reordenado |
| [WayinVideo](https://intercom.help/wayinvideo/en/articles/16209720-what-does-clip-quality-or-viral-score-mean) | Cinco ejes: Hook (primeros segundos), Story (idea completa con remate), Value (útil, sorprendente o emotivo), Engagement (ganas de reaccionar o compartir) y Reach (sirve sin contexto previo) | La rúbrica completa y sus definiciones |
| [ClipsAI](https://www.clipsai.com/references/clip) (abierto) | Segmenta la transcripción con TextTiling sobre embeddings BERT, detectando cambios de tema entre frases | La etapa de segmentación |
| [Clippers de heatmap](https://github.com/0xACAB666/yt-heatmap-clipper) (abiertos) | Cortan donde el gráfico "Lo más repetido" de YouTube tiene picos | Señal de audiencia |

El heatmap no es una señal improvisada: el dataset académico [Mr. HiSum](https://proceedings.neurips.cc/paper_files/paper/2023/hash/7f880e3a325b06e3601af1384a653038-Abstract.html) (NeurIPS 2023) usa "Lo más repetido" como etiqueta de momentos destacados en 31.892 videos, agregando más de 50.000 usuarios por video.

&#91;embedded content: detección de momentos · 9 pasos\]

Las propuestas libres del LLM y las ventanas generadas por reglas se mezclan como candidatos; las señales filtran primero y el juez LLM decide al final.

**Paso 1 — Frases.** Se parte de las frases del 6.2, cada una con inicio y fin.

**Paso 2 — Segmentación temática.** Cada frase se convierte en un embedding con un modelo multilingüe local y gratuito (`paraphrase-multilingual-MiniLM-L12-v2` de sentence-transformers). Se comparan bloques de 6 frases a cada lado de cada punto y se corta donde la similitud cae por debajo de la media menos una desviación estándar, que es la variante con embeddings del TextTiling ([artículo](https://arxiv.org/pdf/2106.12978)). Los capítulos del video, si existen en `info.json`, se agregan como cortes obligatorios.

**Paso 3 — Candidatos.** Dentro de cada tema se generan ventanas que empiezan en un inicio de frase y terminan en un final de frase, con duración de 30 a 90 s. Se agregan tres fuentes extra: las propuestas libres de Gemini sobre la transcripción completa, ventanas centradas en cada pico del heatmap y los temas completos que ya duren 30–90 s.

**Paso 4 — Señales objetivas (de 0 a 1).**

- **Heatmap:** intensidad media del rango, ignorando el primer 5 % del video, donde casi todos los videos tienen un pico porque la gente empieza a verlos. YouTube lo entrega en 100 segmentos y solo existe en videos con suficientes vistas; sin él, su peso se reparte entre las demás señales.
- **Energía de audio:** proporción de segundos con RMS por encima de 1,5 desviaciones de la media del video (risas, gritos, aplausos, énfasis).
- **Densidad:** palabras por segundo, normalizada; los tramos lentos o con silencios largos pierden puntos.
- **Gancho textual:** reglas sobre los primeros 3 s. Suman pregunta directa, números, segunda persona y palabras como "nadie", "error", "secreto", "nunca" o "verdad". Restan arrancar con conectores ("y", "entonces", "pero", "o sea") o con referencias a algo anterior ("eso", "lo que dije").

**Paso 5 — Pre-filtro.** Se calcula un puntaje rápido con las señales y se quedan los 30 mejores candidatos, más todas las propuestas de Gemini. Así el juez LLM evalúa pocos candidatos buenos en vez de cientos.

**Paso 6 — Juez LLM.** Una segunda llamada a Gemini recibe la transcripción completa como contexto y la lista de candidatos con su texto. Califica cada uno de 0 a 10 en los cinco ejes de WayinVideo, cita la frase más fuerte del clip y puede ajustar inicio y fin hasta 10 s. Son dos llamadas por video en total, dentro de la capa gratuita.

**Paso 7 — Puntaje final (0–100).**

```latex
S_{LLM} = 0.30\,Hook + 0.25\,Story + 0.20\,Value + 0.15\,Engagement + 0.10\,Reach
```

```latex
Score = 100 \times \left(0.55\,\tfrac{S_{LLM}}{10} + 0.20\,S_{heatmap} + 0.15\,S_{audio} + 0.10\,S_{gancho}\right)
```

El gancho pesa más porque en Shorts la primera decisión es quedarse o deslizar: la referencia habitual es que 75–80 % de quienes ven el Short se queden y que vean alrededor del 80 % de su duración ([guía de métricas](https://subscribr.ai/youtube-strategy/youtube-shorts-analytics-metrics-viral)).

**Paso 8 — Selección.** Se ordena por puntaje y se descarta todo clip que se solape más de 30 % con uno mejor. Se permiten máximo 2 clips por tema para variar, y se quedan los 8 primeros.

**Paso 9 — Bordes y gancho.** El inicio se ajusta al comienzo de frase y se salta un conector inicial si lo hay; el final, al cierre de frase; después ambos bordes se acercan al silencio más cercano (ver 6.6). Si la frase más fuerte que citó el juez está a mitad del clip, se ofrece como opción anteponer 2–4 s de esa frase al inicio, como hace OpusClip al reordenar.

**Código: segmentación, candidatos y señales**

```python
import re, numpy as np, librosa
from sentence_transformers import SentenceTransformer

EMB = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def topic_cuts(sents, k=6, chapters=()):
    e = EMB.encode([s["text"] for s in sents], normalize_embeddings=True)
    sims = np.array([float(e[i-k:i].mean(0) @ e[i:i+k].mean(0))
                     for i in range(k, len(sents) - k)])
    if len(sims) < 3:
        return []
    thr = sims.mean() - sims.std()
    cuts = {i + k for i in range(1, len(sims) - 1)
            if sims[i] < thr and sims[i] <= sims[i-1] and sims[i] <= sims[i+1]}
    for ch in chapters:                       # capítulos = cortes obligatorios
        cuts.add(min(range(len(sents)), key=lambda j: abs(sents[j]["start"] - ch["start_time"])))
    return sorted(cuts)

def windows(sents, cuts, lo=30, hi=90):
    b = [0, *cuts, len(sents)]
    for a, z in zip(b, b[1:]):
        for i in range(a, z):
            for j in range(i, z):
                d = sents[j]["end"] - sents[i]["start"]
                if d > hi: break
                if d >= lo:
                    yield {"start": sents[i]["start"], "end": sents[j]["end"], "topic": a}

def heat(hm, s, e, dur):
    v = [p["value"] for p in hm or [] if p["end_time"] > s and p["start_time"] < e
         and p["start_time"] > 0.05 * dur]
    return float(np.mean(v)) if v else None   # None = sin heatmap

def audio_profile(wav):
    y, sr = librosa.load(wav, sr=16000)
    rms = librosa.feature.rms(y=y, frame_length=sr, hop_length=sr)[0]   # 1 valor por segundo
    return (rms - rms.mean()) / (rms.std() + 1e-9)

def audio(z, s, e):
    seg = z[int(s):int(e)]
    return float((seg > 1.5).mean()) if len(seg) else 0.0

PLUS = r"\?|\d|\b(tú|te|tu|nadie|nunca|error|secreto|verdad|por qué)\b"
MINUS = r"^(y|entonces|pero|o sea|eso|lo que dije|además)\b"

def hook_rule(words, s):
    first = " ".join(w["w"] for w in words if s <= w["start"] < s + 3).lower()
    score = 0.5 + 0.15 * len(re.findall(PLUS, first)) - 0.4 * bool(re.match(MINUS, first))
    return max(0.0, min(1.0, score))

def nms(clips, max_overlap=0.3, per_topic=2, top=8):
    keep, topics = [], {}
    for c in sorted(clips, key=lambda c: -c["score"]):
        ov = max((min(c["end"], k["end"]) - max(c["start"], k["start"]))
                 / (c["end"] - c["start"]) for k in keep) if keep else 0
        if ov <= max_overlap and topics.get(c["topic"], 0) < per_topic:
            keep.append(c); topics[c["topic"]] = topics.get(c["topic"], 0) + 1
        if len(keep) == top: break
    return keep
```

**Prompt del juez (resumen)**

```text
Eres editor de Shorts y TikTok. Tienes la transcripción completa como contexto
y una lista de candidatos con id, inicio, fin y texto.
Califica cada candidato de 0 a 10 en:
- hook: ¿los primeros 3 s frenan el scroll? (pregunta, afirmación sorprendente,
  emoción fuerte, promesa clara). 0-3 si arranca a mitad de una idea.
- story: ¿se entiende sin ver el video completo y tiene remate (conclusión,
  chiste, revelación, lección)? 0-3 si termina cortado.
- value: ¿es útil, sorprendente, emotivo o identificable?
- engagement: ¿invita a comentar, discutir, guardar o compartir?
- reach: ¿lo entiende alguien que no conoce al creador ni el tema?
Puedes mover inicio y fin hasta 10 s para empezar en la frase más fuerte
y cerrar en el remate. Cita la frase más fuerte en best_line.
Propone un gancho en pantalla (máx. 8 palabras), título con #Shorts,
descripción de 2 líneas y 3-5 hashtags en el idioma del video.
Responde solo JSON según el esquema.
```

**Llamada a Gemini con salida estructurada**

```python
from google import genai
from pydantic import BaseModel

class Judged(BaseModel):
    id: int
    start: float
    end: float
    hook: int
    story: int
    value: int
    engagement: int
    reach: int
    best_line: str
    hook_text: str
    title: str
    description: str
    hashtags: list[str]

client = genai.Client()                       # lee GEMINI_API_KEY

def judge(transcript_text, candidates):
    prompt = JUDGE_PROMPT + "\n\nTRANSCRIPCIÓN:\n" + transcript_text + \
             "\n\nCANDIDATOS:\n" + "\n".join(
                 f'{i}|{c["start"]:.1f}-{c["end"]:.1f}|{c["text"]}' for i, c in enumerate(candidates))
    r = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt,
        config={"response_mime_type": "application/json",
                "response_schema": list[Judged]})
    return r.parsed

def final_score(j, sig):
    llm = .30*j.hook + .25*j.story + .20*j.value + .15*j.engagement + .10*j.reach
    w = {"llm": .55, "heat": .20, "audio": .15, "hook": .10}
    if sig["heat"] is None:                    # sin heatmap: repartir su peso
        w = {"llm": .65, "heat": 0, "audio": .22, "hook": .13}
    return round(100 * (w["llm"] * llm / 10 + w["heat"] * (sig["heat"] or 0)
                        + w["audio"] * sig["audio"] + w["hook"] * sig["hook"]))
```

**Modo "búscame un momento" (como ClipAnything).** Un campo opcional en la pantalla de inicio ("el momento donde habla de dinero") se añade al prompt de propuestas y del juez como criterio extra de relevancia, y los candidatos se ordenan primero por ese criterio.

**Mejora continua.** Los pesos son un punto de partida. Tras publicar, anota en la app el porcentaje "visto vs. deslizado" y el porcentaje promedio visto de cada Short desde YouTube Studio; cuando tengas 20–30 clips, compara qué ejes predijeron mejor el resultado y ajusta los pesos.

### 6.4 Reencuadre 9:16 (módulo de ClipPyMe + diseño dividido de OpenShorts)

Cada escena del clip recibe un diseño fijo según cuántos rostros hay y cuánto se mueven, y la cámara no se mueve dentro de una toma. ClipPyMe explica que el mareo de los recortes automáticos no viene del temblor sino de una cámara que se desplaza todo el tiempo, por eso fija un solo recorte por escena ([README](https://github.com/fralapo/clippyme)).

**Antes de reencuadrar**

1. **Descargar en H.264, no AV1.** OpenShorts tuvo que añadir un respaldo porque el FFmpeg que trae OpenCV no decodifica AV1, y YouTube sirve muchos videos en ese formato ([cambio en OpenShorts](https://github.com/chewtoys/openshorts/pull/35)). En el paso 6.1 se pide `-f "bv*[vcodec^=avc1][height<=1080]+ba/b"`.
2. **Guardar el trozo original 16:9 de cada clip** (`source_<clip>.mp4`). Así, cambiar de diseño en el editor re-renderiza solo ese trozo, como hace ClipPyMe.
3. **Detectar escenas** con PySceneDetect dentro del clip.

**Diseño por escena** (se muestrean 7 cuadros por escena)

| Diseño | Cuándo | Resultado | Origen |
| --- | --- | --- | --- |
| TRACK | Un rostro casi quieto | Recorte fijo sobre la cara, con zoom limitado | ClipPyMe |
| SPLIT | Dos rostros visibles en al menos la mitad de los cuadros muestreados | Dos mitades apiladas, una persona en cada una; subtítulos en la unión | OpenShorts |
| WIDE | Dos o más rostros que no cumplen SPLIT, o una persona que se desplaza más del 12 % del cuadro | Recorte abierto y fijo que deja a todos dentro | ClipPyMe |
| GENERAL | Sin rostros | Video centrado sobre fondo desenfocado | OpenShorts |
| SCREENCAST (opcional) | Pantalla compartida con presentador | Pantalla arriba, presentador abajo | OpenShorts |

La regla de "al menos la mitad de los cuadros" separa una conversación real lado a lado de un montaje plano/contraplano, donde una pantalla dividida mostraría dos veces a la misma persona ([OpenShorts](https://www.openshorts.app/podcast-to-shorts)).

**Quién está hablando.** ClipPyMe detecta personas con YOLOv8 y mide la variación de apertura de la boca con MediaPipe FaceMesh. OpenShorts normaliza esa actividad por persona para que la luz o el contraste no le regalen toda la escena a un lado de la mesa. Con esto se puede, opcionalmente, cortar en seco al que habla en vez de usar SPLIT.

**Parámetros que expone ClipPyMe** (conviene dejarlos en `.env` para ajustarlos sin tocar código)

| Variable | Valor por defecto | Qué controla |
| --- | --- | --- |
| `REFRAME_STATIC_AUTO` | activo | Un solo recorte fijo por escena |
| `REFRAME_MOTION_WIDE_THRESH` | 0,12 | Cuánto puede moverse una persona antes de pasar a WIDE |
| `REFRAME_SPEAKER_SWITCH_MARGIN` | 1,25 | Ventaja que necesita otro hablante para robar el encuadre (evita saltos de ida y vuelta) |
| `REFRAME_MIN_FACE_RATIO` | 0,10 | Ignora caras menores al 10 % de la más grande (público al fondo) |
| `REFRAME_LOST_HOLD` | 90 cuadros | Tiempo (\~3 s) antes de volver suavemente al centro si se pierde al sujeto |

**Subtítulos según el diseño.** El render guarda un archivo `<clip>.layout.json` con los tramos de cada diseño. El generador ASS lo lee: en los tramos SPLIT centra cada palabra en la unión con la etiqueta `\an5`, y en el resto usa la posición normal de la plantilla, como hace OpenShorts ([cambio en OpenShorts](https://github.com/chizee/openshorts-Opus-Clip-Alternatives-/pull/49)).

**En el editor de Next.js.** Un selector por clip (Auto, TRACK, SPLIT, WIDE, Sin recorte) llama a `POST /api/clips/:id/reframe`, que re-renderiza desde el trozo 16:9 guardado en segundos.

### 6.5 Subtítulos animados y gancho

- Generar un archivo `.ass` a partir de `captions.json`: 2–3 palabras por evento, en mayúsculas, con la palabra que se pronuncia resaltada (un evento por palabra con color distinto o etiquetas karaoke `\k`).
- Estilo base: fuente Montserrat ExtraBold 80 px, borde negro de 6 px, posición a un tercio inferior (`MarginV` ≈ 600 en 1920 px).
- El gancho es un segundo estilo en la parte superior, visible de 0 a 3 s, con fondo de caja.
- Cada plantilla es un JSON con fuente, tamaño, colores, animación y posición; el generador ASS la aplica.

### 6.6 Render y acabado (task `render`)

El render sigue el orden y los ajustes de calidad de ClipPyMe: bordes limpios, pocas recodificaciones con la misma calidad, audio normalizado y una revisión automática antes de entregar el MP4 ([README](https://github.com/fralapo/clippyme)).

**1. Bordes que no muerden palabras.** El ajuste del paso 9 del 6.3 lleva inicio y fin a palabra y luego a frase. Después se busca el silencio más cercano con `silencedetect` de ffmpeg y el borde solo se mueve hacia ese silencio; si no hay uno cerca, no cambia. En transcripciones sin puntuación el ajuste a frase no hace nada y queda el de palabra.

```python
import re, subprocess

def snap_to_silence(src, t, window=1.0, noise="-35dB", min_d=0.15):
    """Mueve el tiempo t al centro del silencio más cercano dentro de ±window s."""
    start = max(0.0, t - window)
    log = subprocess.run(
        ["ffmpeg", "-ss", f"{start}", "-t", f"{2*window}", "-i", src,
         "-af", f"silencedetect=noise={noise}:d={min_d}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    mids = [start + (a + b) / 2 for a, b in zip(starts, ends)]
    return min(mids, key=lambda m: abs(m - t)) if mids else t
```

**2. Orden de capas.** Recorte 16:9 → reencuadre → subtítulos → corte inteligente (opcional) → gancho → audio. Los subtítulos se queman antes del corte inteligente para que su tiempo no se desfase cuando se quitan silencios; las capas contiguas se fusionan en una sola pasada de ffmpeg.

**3. Misma calidad en cada pasada.** Todas las codificaciones usan libx264 con CRF 18 y preset `medium` (variables `X264_CRF` y `X264_PRESET`), así las recodificaciones no se acumulan en un video borroso. Con GPU NVIDIA se puede usar `h264_nvenc`, como hace OpenShorts.

**4. Audio a −14 LUFS y arranque rápido.** Normalización EBU R128 al volumen habitual de las redes y `+faststart` para que el MP4 empiece a reproducirse antes de descargarse completo.

```bash
ffmpeg -i reframed.mp4 \
  -vf "ass=clip.ass:fontsdir=fonts" \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11" \
  -c:v libx264 -crf 18 -preset medium -r 30 \
  -c:a aac -b:a 192k -movflags +faststart final.mp4
```

**5. Corte inteligente (opcional).** [auto-editor](https://github.com/WyattBlue/auto-editor) quita silencios y muletillas, como en ClipPyMe. Queda como casilla en el editor porque a veces quita pausas dramáticas que sí funcionan.

**6. Extras de ClipPyMe que vale la pena copiar.** Un zoom lento de 1,00 a 1,05 durante el clip (efecto Ken Burns), la elección automática del cuadro de portada y el nombre del archivo tomado del título sugerido.

**7. Revisión antes de entregar.** Cada render se prueba con ffprobe y filtros de ffmpeg: duración, que existan video y audio, proporción 9:16, porcentaje de cuadros negros o congelados y nivel de audio. Si falla algo crítico se re-renderiza una vez; los avisos menores se guardan en el clip sin borrarlo.

```bash
ffprobe -v error -show_entries stream=codec_type,width,height:format=duration -of json final.mp4
ffmpeg -i final.mp4 -vf "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-60dB:d=2" -an -f null - 2>&1 \
  | grep -E "black_start|freeze_start"
```

### 6.7 Publicación

OpenShorts y ClipPyMe no publican con sus propias apps de YouTube o TikTok: usan un intermediario que ya pasó las auditorías (Upload-Post y Zernio). Esa es la forma de publicar en público sin auditar tu app; se agrega como opción junto al kit manual.

| Ruta | Costo | YouTube | TikTok | Nota |
| --- | --- | --- | --- | --- |
| Kit de publicación + subida manual | 0 | Sí | Sí | Sigue siendo el respaldo |
| [Upload-Post](https://docs.upload-post.com/resources/pricing-and-limits) plan gratis | 0 | Sí, dentro de 10 subidas al mes | No: TikTok exige plan de pago | Pago desde USD 16/mes anual; tope de 10 videos al día en YouTube y 15 en TikTok |
| [Publora](https://skills.sh/publora/skills/tiktok-post) plan gratis | 0 | Verificar | Sí, según su documentación (15 publicaciones al mes) | Probar antes de depender de él |
| Borradores de TikTok con app propia | 0 | — | Borrador, terminas en la app | Ruta de la sección 4 |

Upload-Post [evita registrar una app de TikTok y pasar la auditoría](https://docs.upload-post.com/guides/post-to-tiktok-api/): conectas la cuenta una vez con tu login normal. Ten en cuenta que el creador de OpenShorts [enlaza a Upload-Post en su perfil](https://github.com/mutonby), así que la recomendación dentro de OpenShorts no es neutral.

**Implementación:** un servicio `media/services/publisher.py` con una interfaz común (`publish(clip, title, description, hashtags, when)`) y un proveedor por ruta. Si el intermediario devuelve 429 por tope diario, el clip queda en cola para el día siguiente, como hace ClipPyMe con su programador.

### 6.8 Cola robusta, puntos de control y modelos de respaldo

La cola sigue siendo un hilo local con SQLite, pero adopta las protecciones de ClipPyMe para no perder trabajo ni cuota ([README](https://github.com/fralapo/clippyme)).

- **Puntos de control por fase:** descarga, transcripción, análisis y cada clip terminado se guardan en la carpeta del proyecto con escritura atómica. Un reintento o un reinicio reutiliza lo hecho en vez de repetirlo.
- **Reintentos acotados:** hasta 3 con espera creciente; los errores de validación (URL inválida, video privado) no se reintentan.
- **Revisión previa:** antes de gastar, se miden duración, espacio libre en disco y tokens estimados; si algo no alcanza, el proyecto se rechaza al inicio.
- **Clips a medida que terminan:** cada clip aparece en la interfaz apenas se renderiza, y hay botones de pausar, detener conservando lo hecho o descartar.
- **Cadena de modelos Gemini:** si un modelo responde por cuota agotada, se prueba el siguiente de `GEMINI_FALLBACK_MODELS` (por ejemplo `gemini-2.5-flash,gemini-2.5-flash-lite`); cada proyecto nuevo vuelve a empezar por el preferido.
- **Lectura tolerante del JSON:** quitar bloques de código, extraer el primer objeto JSON, reparar comas sobrantes y validar con Pydantic antes de reintentar la llamada.
- **Ollama como alternativa real:** cualquier servidor compatible con OpenAI vía `LLM_BASE_URL` y `LLM_MODEL`. OpenShorts advierte que Ollama usa por defecto 4.096 tokens de contexto y recorta sin avisar, así que hay que subirlo con `OLLAMA_CONTEXT_LENGTH=16384`, y que los modelos de 7–8B devuelven JSON válido de forma fiable mientras los de 3B no ([README](https://github.com/mutonby/openshorts)).
- **Solo en tu PC:** ambos servicios escuchan en `127.0.0.1`, igual que ClipPyMe por defecto.

## 7. Estructura del proyecto

Una carpeta con dos aplicaciones, `web` (Next.js) y `media` (Python), que comparten la carpeta `data/` y se arrancan con un solo comando.

```text
clipper/
├─ web/                            # Next.js (App Router, TypeScript)
│  ├─ app/
│  │  ├─ page.tsx                    # input de URL / subir archivo + lista de proyectos
│  │  ├─ projects/[id]/page.tsx      # progreso + clips candidatos
│  │  ├─ clips/[id]/page.tsx         # editor + kit de publicación
│  │  └─ api/
│  │     ├─ projects/route.ts          # POST crear, GET listar
│  │     ├─ projects/[id]/route.ts     # GET estado y clips
│  │     ├─ clips/[id]/route.ts        # PATCH editar clip
│  │     ├─ clips/[id]/render/route.ts # encola render
│  │     └─ clips/[id]/tiktok/route.ts # encola borrador (opcional)
│  ├─ components/                   # ClipCard, Timeline, CaptionEditor, TemplatePicker, CopyField
│  ├─ lib/ (db.ts, media.ts)
│  └─ prisma/schema.prisma
├─ media/                          # Python 3.11
│  ├─ main.py                       # FastAPI: POST /jobs, GET /files, hilo de trabajo
│  ├─ tasks/ (download.py, transcribe.py, analyze.py, reframe.py, render.py, tiktok.py)
│  ├─ services/ (gemini.py, ass_builder.py, scoring.py, db.py)
│  ├─ templates/*.json              # plantillas de subtítulos
│  ├─ fonts/
│  └─ requirements.txt
├─ data/                           # app.db + proyectos (no subir a git)
├─ .env
└─ start.sh / start.bat            # arranca web y media juntos
```

**Carpetas nuevas por la reutilización**

```text
media/
├─ vendor/
│  ├─ clippyme/            # submódulo git fijado a un commit (MIT)
│  └─ NOTICE.md            # qué se tomó, de qué commit, con qué licencia
└─ services/
   ├─ reframe_adapter.py   # única puerta hacia ClipPyMe + SPLIT de OpenShorts
   ├─ cut_ops.py           # bordes palabra → frase → silencio (adaptado de ClipPyMe)
   ├─ json_repair.py       # lectura tolerante del JSON de Gemini
   ├─ media_qa.py          # revisión del render
   └─ publisher.py         # kit manual | Upload-Post | borrador TikTok
```

Nuevas variables en `.env`: `GEMINI_FALLBACK_MODELS`, `LLM_BASE_URL`, `LLM_MODEL`, `X264_CRF`, `X264_PRESET`, las `REFRAME_*` del 6.4 y, si usas un intermediario, `UPLOAD_POST_API_KEY`.

**Endpoints**

| Método y ruta | Servicio | Qué hace |
| --- | --- | --- |
| `POST /api/projects` | Next.js | Crea el proyecto (URL o archivo) y llama a `POST /jobs` |
| `GET /api/projects/:id` | Next.js | Estado, progreso y clips |
| `PATCH /api/clips/:id` | Next.js | Guarda bordes, subtítulos, gancho, plantilla, textos |
| `POST /api/clips/:id/render` | Next.js | Encola el render |
| `POST /api/clips/:id/tiktok` | Next.js | Encola el envío a borradores (opcional) |
| `POST /jobs` | FastAPI | Registra el job en SQLite para el hilo de trabajo |
| `GET /files/...` | FastAPI | Sirve videos, clips y miniaturas de `data/` |

**Variables de entorno (`.env`)**

| Variable | Uso | ¿Obligatoria? |
| --- | --- | --- |
| `DATABASE_URL` | Ruta del archivo SQLite | Sí |
| `DATA_DIR` | Carpeta de proyectos | Sí |
| `MEDIA_API_URL` | `http://127.0.0.1:8000` | Sí |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Selección de momentos | Sí |
| `WHISPER_MODEL`, `WHISPER_DEVICE` | `large-v2` + `cuda`, o `small` + `cpu` | Sí |
| `HF_TOKEN` | Diarización | No |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | Borradores en TikTok | No |

**Arranque:** `start.sh` ejecuta `uvicorn media.main:app --host 127.0.0.1 --port 8000` y `npm run dev` en `web/`. Requisitos previos: Node.js LTS, Python 3.11, FFmpeg y Deno instalados.

## 8. Plan de desarrollo paso a paso

Trabajando solo a tiempo parcial, en 6 semanas tienes la herramienta funcionando y tus primeros Shorts publicados; cada fase termina con una prueba concreta antes de seguir.

&#91;embedded content: roadmap · 4 fases, 3 puertas\]

La Fase 1 es la más importante: si la IA no elige buenos momentos, la interfaz no sirve de nada, así que se valida con un script antes de construir la app.

| Semana | Entregables | Listo cuando |
| --- | --- | --- |
| 1 | Instalar Node.js, Python, FFmpeg y Deno. Script `download` + `transcribe` | Un video de 1 hora genera su `transcript.json` con tiempos por palabra |
| 2 | Script `analyze` con Gemini + render simple (recorte central + subtítulos ASS) | En 5 videos, al menos 7 de cada 10 clips te parecen publicables |
| 3 | Next.js + Prisma con SQLite + FastAPI con hilo de trabajo; pantalla de inicio y progreso | Pegas una URL y ves avanzar el proyecto hasta `READY` |
| 4 | Lista de clips con preview; integrar el reencuadre de ClipPyMe con el adaptador y el diseño SPLIT de OpenShorts; 3 plantillas de subtítulos | Cada clip sale en 1080×1920 con el rostro centrado y subtítulos sincronizados |
| 5 | Editor: bordes, palabras, gancho, plantilla; kit de publicación con botones de copiar | Corriges un clip y lo vuelves a renderizar sin tocar la terminal |
| 6 | Script `start`, botón "Limpiar"; opcional: Upload-Post o borradores de TikTok | Subes tus primeros 10 Shorts a YouTube y TikTok |

**Fase 4 · Mejoras cuando las necesites**

1. Revisar en YouTube Studio qué clips retienen mejor y ajustar los pesos del puntaje y el prompt.
2. Plantillas animadas con Remotion (emojis, zoom, rebote), gratis para uso individual.
3. Pantalla dividida para dos personas y ajuste manual del recorte.
4. Búsqueda de momentos por instrucción ("el momento donde habla de dinero").
5. Subida automática a YouTube si decides pedir la auditoría de la API.

## 9. Reglas a tener en cuenta

Que la herramienta sea personal elimina auditorías, pagos y privacidad de terceros, pero no cambia las reglas sobre el contenido que publicas: subir clips de videos ajenos sigue expuesto a reclamos de copyright aunque no cobres. Esto es orientativo, no asesoría legal.

| Tema | Qué dice la regla | Qué hacer |
| --- | --- | --- |
| Descarga desde YouTube | Los [Términos de YouTube](https://www.youtube.com/terms) no permiten descargar contenido salvo lo que el servicio permite, con permiso escrito o lo que autorice la ley | Prefiere subir tus propios archivos; para videos de otros, obtén su permiso |
| Derechos de autor | Publicar clips de terceros sin permiso puede traer reclamos, retiradas y strikes en tu canal | Clipea tu propio contenido o el de creadores que autoricen el clipping (algunos tienen programas abiertos para clippers) y da crédito |
| Monetización en YouTube | Los clips editados con poca o ninguna narrativa no se monetizan, aun con permiso del creador ([política](https://support.google.com/youtube/answer/1311392)) | Añade valor propio: gancho, título, contexto o comentario, no solo el corte |
| Subidas por API | Sin auditoría, YouTube bloquea como privados los videos subidos por API y TikTok limita Direct Post a privado | Subida manual o borradores de TikTok (sección 4) |
| Tus claves | La API key de Gemini y los tokens dan acceso a tus cuentas | Guárdalas en `.env`, excluye `.env` y `data/` de git y no compartas la carpeta |

## 10. Costos

El costo mensual es USD 0 usando tu PC y la capa gratuita de Gemini; aunque pasaras a Gemini de pago, un video de una hora costaría alrededor de un centavo de dólar.

| Concepto | Opción elegida | Costo (USD/mes) | Alternativa si la necesitas |
| --- | --- | --- | --- |
| Servidor | Tu PC (`localhost`) | 0 | — |
| Base de datos | SQLite | 0 | Supabase, plan gratuito |
| Almacenamiento | Disco local (1–2 GB por proyecto hasta limpiarlo) | 0 | Disco externo |
| Descarga | yt-dlp | 0 | — |
| Transcripción | WhisperX local (GPU o CPU) | 0 | API de transcripción de pago si tu PC es muy lenta |
| Selección de clips | Gemini 2.5 Flash, capa gratuita | 0 | Gemini de pago o Ollama local |
| Render y subtítulos | FFmpeg + ASS | 0 | Remotion, gratis para individuos |
| Publicación | Manual, Upload-Post gratis (10 subidas al mes, sin TikTok) o borradores de TikTok | 0 | — |
| Dominio, hosting, pagos | No se necesitan | 0 | — |

**Cálculo con Gemini de pago:** 2.5 Flash cuesta USD 0,30 por millón de tokens de entrada y USD 2,50 por millón de salida ([referencia, julio 2026](https://www.rapidevelopers.com/md/ai-api-limits-performance-matrix/gemini-2-5-flash)). Una transcripción de una hora (unos 20.000 tokens) más una respuesta de unos 2.000 tokens suman cerca de USD 0,01.

**Comparación:** OpusClip Pro cuesta USD 29 al mes por 300 minutos de video ([desglose de precios](https://www.castmagic.io/blog/opus-clip-pricing)); tu herramienta procesa sin límite de minutos por el costo de la electricidad.

**Único gasto que podría valer la pena:** si tu PC no tiene GPU y transcribir una hora tarda demasiado, puedes usar un modelo más pequeño (`small`) o procesar videos mientras no usas la computadora antes de pagar cualquier servicio.

## 11. Riesgos y checklist de arranque

Para un proyecto personal quedan cinco riesgos, todos con solución gratuita.

| Riesgo | Probabilidad | Impacto | Qué hacer |
| --- | --- | --- | --- |
| La IA elige clips poco atractivos | Media | Alto | Prueba de la semana 2, iterar el prompt con ejemplos reales y apoyarse en el heatmap |
| PC lenta sin GPU | Media | Medio | Modelo `small` en CPU y dejar videos procesándose mientras no usas la PC |
| YouTube cambia algo y yt-dlp falla | Media | Medio | `yt-dlp -U` semanal; como último recurso `--cookies-from-browser`; o subir el archivo |
| Reclamos de copyright al publicar | Alta si clipeas contenido ajeno sin permiso | Alto | Contenido propio o autorizado y valor añadido (sección 9) |
| Se agota la capa gratuita de Gemini | Baja | Bajo | Un solo pedido por video; Ollama como respaldo |

**Checklist de la primera semana**

- [ ] Elegir el nicho inicial (por ejemplo podcasts y entrevistas en español) y reunir 5 videos de prueba con permiso.
- [ ] Crear la carpeta del proyecto con `web/` y `media/`.
- [ ] Instalar Node.js LTS, Python 3.11, FFmpeg y Deno, y comprobar que cada uno responde en la terminal.
- [ ] Crear tu API key gratuita de Gemini en Google AI Studio.
- [ ] Revisar si tu PC tiene GPU NVIDIA y elegir el modelo de Whisper: large-v2 con GPU, small en CPU.
- [ ] Crear el archivo .env y añadir .env y data/ al .gitignore.
- [ ] Opcional: crear token de Hugging Face y aceptar el acuerdo del modelo de diarización.
- [ ] Clonar [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) y correrlo en modo local con los 5 videos como línea base.
- [ ] Escribir el prompt de selección y el esquema JSON; comparar sus clips con los de la línea base.
- [ ] Definir la plantilla de subtítulos principal en ASS y renderizar el primer clip 1080×1920.

## 12. Referencias

**Plataformas de referencia**

- [OpusClip](https://www.opus.pro) · [WayinVideo](https://wayin.ai) · [Remakeit](https://remakeit.io)
- [Precios de OpusClip 2026 (Castmagic)](https://www.castmagic.io/blog/opus-clip-pricing)

**Publicación**

- [YouTube Data API: videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube: videos bloqueados como privados](https://support.google.com/youtube/answer/7300965?hl=en)
- [YouTube: formulario de auditoría de la API](https://support.google.com/youtube/contact/yt_api_form)
- [TikTok: Upload a borradores (inbox)](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video)
- [TikTok: Direct Post y límites sin auditoría](https://developers.tiktok.com/doc/content-sharing-guidelines/)

**Reglas**

- [Términos de servicio de YouTube](https://www.youtube.com/terms)
- [Políticas de monetización de YouTube (contenido reutilizado)](https://support.google.com/youtube/answer/1311392)

**Procesamiento**

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [heatmap en yt-dlp](https://github.com/yt-dlp/yt-dlp/issues/3888)
- [WhisperX](https://github.com/m-bain/whisperX) · [faster-whisper](https://github.com/SYSTRAN/faster-whisper) · [pyannote-audio](https://github.com/pyannote/pyannote-audio)
- [MediaPipe Face Detector](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector) · [OpenCV](https://docs.opencv.org) · [PySceneDetect](https://www.scenedetect.com) · [librosa](https://librosa.org/doc/latest/)
- [FFmpeg](https://ffmpeg.org/documentation.html) · [Etiquetas ASS](https://aegisub.org/docs/latest/ass_tags/) · [Remotion: licencia](https://www.remotion.dev/docs/pricing)

**IA**

- [Gemini API](https://ai.google.dev/gemini-api/docs) · [Cómo obtener la API key y límites gratuitos](https://www.apideck.com/blog/how-to-get-your-gemini-api-key) · [Precios de Gemini 2.5 Flash](https://www.rapidevelopers.com/md/ai-api-limits-performance-matrix/gemini-2-5-flash)
- [Ollama](https://ollama.com)

**Aplicación**

- [Next.js](https://nextjs.org/docs) · [Prisma con SQLite](https://www.prisma.io/docs/orm/overview/databases/sqlite) · [Tailwind CSS](https://tailwindcss.com/docs) · [shadcn/ui](https://ui.shadcn.com) · [TanStack Query](https://tanstack.com/query/latest)
- [FastAPI](https://fastapi.tiangolo.com) · [Supabase (opcional)](https://supabase.com/docs)

**Código abierto para estudiar**

- [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator): modo local con yt-dlp, faster-whisper, FFmpeg/OpenCV y ranking con Gemini u OpenAI.
- [ClipForge](https://github.com/JeremySNR/clip-forge): alternativa de escritorio con puntaje de viralidad, subtítulos animados y reencuadre por hablante.
- [Tema opus-clip-alternative en GitHub](https://github.com/topics/opus-clip-alternative).

**Transcripción y detección de momentos**

- [yt-dlp: guía de PO Token (subtítulos incluidos)](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) · [json3 y duplicados aAppend](https://lobehub.com/mcp/pobibibi-youtube-transcript-mcp)
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) · [Transcripciones sin la Data API: límites en 2026](https://dev.to/xixisuperman/getting-youtube-transcripts-without-the-data-api-and-why-translate-to-100-languages-is-usually-43m8)
- [Estudio de precisión de subtítulos automáticos (264 videos)](https://youtube-transcript.ai/blog/youtube-auto-caption-accuracy-study) · [Subtítulos de YouTube vs. Whisper](https://mdisbetter.com/blog/youtube-auto-captions-vs-ai-transcription)
- [OpusClip: cómo se calcula el Virality Score](https://help.opus.pro/docs/article/virality-score) · [WayinVideo: qué significa el Viral Score](https://intercom.help/wayinvideo/en/articles/16209720-what-does-clip-quality-or-viral-score-mean)
- [ClipsAI: segmentación con TextTiling](https://www.clipsai.com/references/clip) · [TextTiling con embeddings BERT (artículo)](https://arxiv.org/pdf/2106.12978)
- [Mr. HiSum: "Lo más repetido" como etiqueta de highlights (NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/hash/7f880e3a325b06e3601af1384a653038-Abstract.html) · [yt-heatmap-clipper](https://github.com/0xACAB666/yt-heatmap-clipper)
- [Métricas de Shorts: visto vs. deslizado y porcentaje visto](https://subscribr.ai/youtube-strategy/youtube-shorts-analytics-metrics-viral)

**Proyectos reutilizados**

- [ClipPyMe](https://github.com/fralapo/clippyme) · [licencia MIT](https://github.com/fralapo/clippyme/blob/main/LICENSE)
- [OpenShorts](https://github.com/mutonby/openshorts) · [diseño de dos personas en podcasts](https://www.openshorts.app/podcast-to-shorts) · [subtítulos en la unión del SPLIT](https://github.com/chizee/openshorts-Opus-Clip-Alternatives-/pull/49) · [respaldo para videos AV1](https://github.com/chewtoys/openshorts/pull/35)
- [Upload-Post: precios y límites](https://docs.upload-post.com/resources/pricing-and-limits) · [publicar en TikTok sin auditoría propia](https://docs.upload-post.com/guides/post-to-tiktok-api/)
