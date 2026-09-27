# ClipAI

Herramienta personal de clipping con IA que corre en tu computadora. Pegas una URL
de YouTube o subes un video; ClipAI elige los momentos más fuertes, los convierte en
clips verticales 9:16 de 30–90 s con subtítulos animados y texto gancho, y te deja
el MP4 con título, descripción y hashtags listos para subir a Shorts o TikTok.

Todo corre en `127.0.0.1`: sin cuentas, sin nube. Solo salen a internet la descarga
del video, la llamada a la IA (Gemini, opcional) y, si la activas, la publicación.

## Instalación (macOS con Homebrew)

```bash
brew install node python@3.11 deno ffmpeg-full
```

- **ffmpeg-full** (y no `ffmpeg`): el `ffmpeg` normal de Homebrew no trae libass y sin
  libass no se pueden quemar los subtítulos. `ffmpeg-full` se instala aparte y no
  reemplaza al otro; ClipAI lo encuentra solo.
- **Deno**: yt-dlp lo usa para resolver los retos de JavaScript de YouTube.

Luego, en la carpeta del proyecto:

```bash
cp .env.example .env        # opcional: start.sh lo crea si no existe
# edita .env y pon tu GEMINI_API_KEY (gratis en https://aistudio.google.com/apikey)
./start.sh
```

La primera vez `start.sh` crea el entorno de Python, instala las dependencias
(≈ 3 GB con PyTorch), aplica las migraciones de SQLite y compila la interfaz. Después
arranca los dos servicios y abre http://127.0.0.1:3000. `Ctrl+C` los detiene.

```bash
./start.sh --no-install   # arranque rápido, sin revisar dependencias
./start.sh --dev          # interfaz en modo desarrollo (recarga en caliente)
```

La primera transcripción descarga el modelo de Whisper (`small`, ~480 MB) y la primera
segmentación el modelo de embeddings (~470 MB); después funciona sin conexión.

**Windows:** instala Python 3.11, Node.js LTS, Deno y un FFmpeg «full» (con libass,
p. ej. de gyan.dev) en el PATH y ejecuta `start.bat`.

## Uso

1. Pega un enlace de YouTube (o arrastra un MP4/MOV) y pulsa **Crear clips**.
   Opcional: **Buscar un momento concreto** («cuando habla de dinero»).
2. El proyecto avanza por descarga → transcripción → búsqueda de momentos. Puedes
   pausarlo, detenerlo conservando lo hecho o descartarlo.
3. Los clips aparecen ordenados por puntaje y se renderizan solos (`AUTO_RENDER=1`).
4. En el editor ajustas bordes, corriges palabras (doble clic), cambias el gancho, la
   plantilla y el encuadre (Automático, Una persona, Dos personas, Plano abierto,
   Sin recorte) y pulsas **Guardar y renderizar**.
5. Copia título, descripción y hashtags y descarga el MP4. Márcalo como subido.
6. **Limpiar** borra los videos fuente de los proyectos terminados para ahorrar disco.

## Configuración

Todas las variables están comentadas en [.env.example](.env.example). Las más útiles:

| Variable | Para qué |
| --- | --- |
| `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `GOOGLE_SERVICE_ACCOUNT_FILE` (o `_JSON`) | Gemini en Vertex AI con cuenta de servicio (rol «Vertex AI User»). Tiene prioridad sobre la API key. Vertex cobra por uso (sin capa gratuita de AI Studio). |
| `GEMINI_API_KEY` | Gemini API de AI Studio (capa gratuita). Sin Vertex ni clave funciona el respaldo sin IA (TextTiling + señales). También se lee del entorno del shell. |
| `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS` | Cadena de modelos: si uno responde 429/503/404 se prueba el siguiente. |
| `LLM_BASE_URL`, `LLM_MODEL` | Ollama u otro servidor compatible con OpenAI en lugar de Gemini. |
| `WHISPER_MODEL`, `WHISPER_DEVICE` | `small` + `cpu` sin GPU; `large-v3` + `cuda` con NVIDIA. |
| `MAX_CLIPS`, `CLIP_MIN_SEC`, `CLIP_MAX_SEC` | Cuántos clips y de qué duración. |
| `AUTO_RENDER` | Renderizar solos los clips elegidos. |
| `X264_CRF`, `X264_PRESET`, `VIDEO_ENCODER` | Calidad y velocidad del render (`h264_videotoolbox` en Mac). |
| `REFRAME_*`, `SPLIT_LAYOUT`, `SPEAKER_CUT` | Ajustes del reencuadre (plan 6.4). |
| `YTDLP_COOKIES_FROM_BROWSER` | Si YouTube pide verificar que no eres un bot. |

### Publicación opcional

- **Upload-Post**: pon `UPLOAD_POST_API_KEY` y `UPLOAD_POST_USER`; aparece el botón
  «Publicar en YouTube con Upload-Post». Si llegas al tope, se reprograma para mañana.
- **Borradores de TikTok**: registra una app en TikTok for Developers (Login Kit +
  Content Posting API, scope `video.upload`), pon `TIKTOK_CLIENT_KEY`,
  `TIKTOK_CLIENT_SECRET` y `TIKTOK_REDIRECT_URI` (debe coincidir con el registrado; si
  TikTok exige HTTPS usa un túnel como ngrok) y pulsa «Conectar TikTok» una vez. El
  token se guarda cifrado en `data/secrets/`.

## Cómo funciona

```text
web/   Next.js (UI + Route Handlers + Prisma/SQLite)
  └─ POST /jobs ─▶ media/  FastAPI + hilo de trabajo (cola en SQLite)
                     download ─▶ transcribe ─▶ analyze ─▶ render
data/  app.db + projects/<id>/ (source.mp4, audio.wav, transcript.json, clips/<id>/…)
```

- **Transcripción**: subtítulos de YouTube (manuales antes que automáticos, formato
  json3) para analizar; Whisper solo para pulir los clips elegidos.
- **Momentos**: TextTiling con embeddings → candidatos de 30–90 s → señales (heatmap,
  energía de audio, densidad, gancho) → juez Gemini con 5 ejes → puntaje → NMS →
  bordes limpios (palabra → frase → silencio).
- **Reencuadre**: módulo de ClipPyMe (cámara quieta por escena) + diseño SPLIT de
  OpenShorts. Qué se reutilizó y por qué: [docs/reuse-map.md](docs/reuse-map.md).
- **Render**: subtítulos ASS, −14 LUFS, CRF compartido, `+faststart` y revisión de
  calidad antes de entregar.

## Tests

```bash
.venv/bin/pytest -q                    # unitarios (sin red)
.venv/bin/pytest -m e2e -s             # punta a punta con un video real (~5 min)
cd web && npm run lint && npx tsc --noEmit
```

## Problemas comunes

- **403 o «Sign in to confirm you're not a bot»**: actualiza yt-dlp (`start.sh` lo hace
  cada semana) o define `YTDLP_COOKIES_FROM_BROWSER=chrome`.
- **Gemini 404 «no longer available to new users»** (API key): tu cuenta no tiene ese
  modelo; la cadena `GEMINI_FALLBACK_MODELS` pasa al siguiente. En Vertex
  `gemini-2.5-flash` sí está disponible; los modelos 3.x solo existen en el endpoint
  `global` y la app los reintenta ahí sola.
- **npm con `ignore-scripts=true`**: `start.sh` compila solo `better-sqlite3` con
  scripts habilitados; no cambia tu configuración global.
- **Avisos de Hugging Face o MediaPipe en la terminal**: son inofensivos. Los modelos se
  cargan desde la caché local tras la primera descarga y `start.sh` filtra los avisos de
  arranque de MediaPipe.
- Los registros del servicio están en `data/logs/media.log`.

## Aviso

Descargar y publicar videos de terceros puede infringir los Términos de YouTube y
derechos de autor. Usa tu propio contenido o el de creadores que lo autoricen.
