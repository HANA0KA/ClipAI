// Formas que devuelven los Route Handlers (compartidas por servidor y cliente).
import type { EditDoc, Segment } from "@/lib/edit-doc";

export type ProjectStatus =
  | "QUEUED" | "UPLOADING" | "DOWNLOADING" | "TRANSCRIBING" | "ANALYZING"
  | "READY" | "FAILED" | "PAUSED" | "STOPPED";

export type RenderStatus = "NONE" | "QUEUED" | "RUNNING" | "DONE" | "FAILED";
export type LayoutMode = "auto" | "track" | "split" | "wide" | "off";

export interface ProjectDTO {
  id: string;
  sourceType: "youtube" | "kick" | "upload";
  sourceUrl: string | null;
  title: string | null;
  durationSec: number | null;
  language: string | null;
  status: ProjectStatus;
  progress: number;
  stage: string | null;
  error: string | null;
  query: string | null;
  transcriptSource: string | null;
  llmProvider: string | null;
  thumbUrl: string | null;
  sourceVideoUrl: string | null;
  sourceDeleted: boolean;
  aiCostUsd: number;
  aiTokens: number;
  aiCostEstimated: boolean;
  /** Plantilla de subtítulos del proyecto (null = automática, aún sin resolver). */
  templateId: string | null;
  /** Si solo se descargó un tramo del video (directos largos de Kick): [inicio, fin] en segundos del original. */
  rangeStartSec: number | null;
  rangeEndSec: number | null;
  createdAt: string;
  clipCount: number;
  clipsRendered: number;
}

export interface ClipSignals {
  heat?: number | null;
  audio?: number;
  density?: number;
  hook?: number;
  pause?: number;
  source?: string;
  edges?: string;
  judge?: { hook: number; story: number; value: number; engagement: number; reach: number } | null;
  relevance?: number | null;
  /** Estructura del clip: gancho → contexto → desarrollo → remate. */
  arc?: {
    source: "llm" | "heuristic" | "candidate";
    hook?: string;
    context?: string;
    payoff?: string;
    reason?: string;
    hook_options?: string[]; // otras versiones del gancho en pantalla (sin defectos)
    cold_open?: boolean;
    hook_seconds?: number | null; // segundos del gancho hablado
    duration?: number; // lo que pidió la historia
  } | null;
}

export type Platform = "tiktok" | "instagram" | "youtube";
export type HashtagSets = Record<Platform, string[]>;

export type CoverPosition = "top" | "center" | "bottom";
export type CoverStyle = "outline" | "box";

/** Ajustes de la portada (media/services/cover.py). `text` null = el gancho;
 * `time` (segundo del video fuente) null = el mejor cuadro automático. */
export interface CoverSettings {
  text: string | null;
  time: number | null;
  position: CoverPosition;
  style: CoverStyle;
  dim: boolean;
}

export interface PublishInfo {
  provider?: string;
  url?: string | null;
  note?: string;
  error?: string;
  retryAt?: string;
  caption?: string;
}

export interface ClipDTO {
  id: string;
  projectId: string;
  rank: number;
  startSec: number;
  endSec: number;
  score: number;
  reason: string;
  hook: string;
  hookType: string | null;
  title: string;
  description: string;
  hashtags: string;
  hashtagSets: HashtagSets | null;
  templateId: string;
  layoutMode: LayoutMode;
  smartCut: boolean;
  prependBestLine: boolean;
  durationSec: number; // duración del clip editado (suma de tramos)
  segmentCount: number;
  aspect: "vertical" | "square" | "original";
  bestLine: string | null;
  bestLineStart: number | null;
  bestLineEnd: number | null;
  renderStatus: RenderStatus;
  renderError: string | null;
  renderProgress: number;
  editRevision: number;
  renderedRevision: number;
  videoUrl: string | null;
  thumbUrl: string | null;
  downloadUrl: string | null;
  coverUrl: string | null; // portada JPG con el gancho en grande
  coverDownloadUrl: string | null;
  cover: CoverSettings;
  qaWarnings: string[];
  signals: ClipSignals;
  publishStatus: string | null;
  publishInfo: PublishInfo | null;
  postedAt: string | null;
  createdAt: string;
  updatedAt: string;
  /** Posición en el orden de publicación del proyecto (1 = publicar primero). */
  order: number | null;
  /** Nombre base de sus archivos: «03 - Título» (video .mp4 y «… - portada.jpg»). */
  fileBase: string;
}

/** Palabra de captions.json; ``t`` (su inicio, 3 decimales) es su identidad. */
export interface CaptionWord {
  t: number;
  w: string;
  start: number;
  end: number;
  hl: boolean;
}

/** Estado del clip tal como salió del análisis («Restaurar original»). */
export interface OriginalSnapshot {
  hook: string;
  title: string;
  description: string;
  hashtags: string;
  templateId: string;
  layoutMode: LayoutMode;
  smartCut: boolean;
  segments: Segment[];
  words: { t: number; w: string; hl: boolean }[];
}

export interface ClipDetail {
  clip: ClipDTO;
  project: ProjectDTO;
  captions: {
    source: string; edited: boolean; range: [number, number] | null; words: CaptionWord[];
    /** Palabras de la transcripción que el pulido con Whisper se saltó dentro del clip (lib/gapfill.ts). */
    missing: number;
  };
  doc: EditDoc;
  original: OriginalSnapshot;
}

export interface TemplateInfo {
  id: string;
  name: string;
  description: string;
  font: string;
  highlight: string;
  primary: string;
  emphasis?: string | null;
  uppercase?: boolean | null;
  animation?: string | null;
  box_color?: string | null;
  background?: string | null;
  entrance?: string | null;
  emoji?: boolean | null;
  hookDuration?: number | null; // segundos mínimos del gancho en pantalla
}

export interface FontInfo {
  file: string;
  family: string;
  style: string;
  name: string; // nombre para el estilo ASS (y para la vista previa)
  builtin: boolean;
  url: string;
}

export interface TimelineAssets {
  start: number;
  end: number;
  count: number;
  interval: number;
  thumbs: string;
  thumbW: number;
  thumbH: number;
  peaks: number[];
}

export interface Health {
  ok: boolean;
  ffmpeg?: string;
  libass?: boolean;
  deno?: boolean;
  ytdlp?: string | null;
  llm?: string;
  llmConfigured?: boolean;
  whisper?: string;
  autoRender?: boolean;
  clipMinSec?: number;
  clipMaxSec?: number;
  emoji?: boolean;
  hashtagsBase?: string[]; // fijos del canal (HASHTAGS_BASE)
  hashtagsCreator?: boolean; // hashtag del creador del video original
  worker?: { alive: boolean; current: { type: string; targetId: string } | null };
  queue?: Record<string, number>;
  publishers?: { name: string; label: string; available: boolean; connected?: boolean }[];
  diskFreeGb?: number;
  error?: string;
}

/** Video de YouTube con su potencial para clips (media/services/trending.py). */
export interface TrendingItem {
  id: string;
  url: string;
  title: string;
  channel: string;
  thumbnail: string;
  views: number | null;
  likes: number | null;
  comments: number | null;
  uploadedAt: string | null;
  ageDays: number | null;
  durationSec: number;
  followers: number | null;
  chapters: number;
  subtitles: "manual" | "auto" | null;
  language: string | null;
  topics: string[];
  partial: boolean;
  score: number;
  tier: "muy alto" | "alto" | "medio" | "bajo";
  reasons: string[];
  warnings: string[];
  parts: { momentum: number; outperform: number; engagement: number; clips: number };
  /** Proyecto de ClipAI que ya usa este video (null = aún no). */
  project: string | null;
}

export interface TrendingResponse {
  items: TrendingItem[];
  topics: string[];
  defaultLang: string | null;
  meta: {
    queries: string[]; period: string; sort: string; duration: string | null; lang: string | null;
    hidden: Record<string, number>;
    found: number; cached: boolean; at: number;
  };
}

/** Lo que dice /api/source-info de un enlace de Kick (media/services/sources.py). */
export interface KickVodInfo {
  type: "kick";
  kind: "video";
  id: string;
  title: string;
  channel: string;
  duration: number;
  uploadedAt: string | null;
  views: number | null;
  thumbnail: string | null;
  live: boolean;
  maxMinutes: number;
  tooLong: boolean;
}

export interface KickChannelVods {
  type: "kick";
  kind: "channel";
  channel: string;
  /** Perfil público del canal (null si Kick no lo dio: los VODs se listan igual). */
  profile: { name: string; avatar: string | null; followers: number | null; verified: boolean; live: string | null } | null;
  vods: { id: string; url: string; title: string; createdAt: string | null; durationSec: number; views: number | null; live: boolean; thumbnail: string | null }[];
}

/** Videos recientes de un canal de YouTube (listado plano: sin fecha, con miniatura fija por id). */
export interface YoutubeChannelVideos {
  type: "youtube";
  kind: "channel";
  /** Clave del canal: «@handle», «channel/UC…», «c/nombre» o «user/nombre». */
  channel: string;
  tab: "videos" | "streams";
  profile: { name: string; avatar: string | null; followers: number | null; verified: boolean; handle: string | null };
  videos: { id: string; url: string; title: string; durationSec: number; views: number | null; thumbnail: string; live: boolean; tooLong: boolean; membersOnly: boolean }[];
  maxMinutes: number;
  /** El canal no tiene esa pestaña (p. ej. sin directos): la lista viene vacía, con su perfil. */
  missingTab: boolean;
}

export type SourceInfo = KickVodInfo | KickChannelVods | YoutubeChannelVideos | { type: "youtube"; kind: "video"; id: string };

/** Lo que se publica de un clip: el gancho de la portada más el nombre del creador del video original. */
export interface PublishText {
  creator: string | null;
  title: string;
  description: string;
  hashtags: string;
}
