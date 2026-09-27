// Formas que devuelven los Route Handlers (compartidas por servidor y cliente).

export type ProjectStatus =
  | "QUEUED" | "UPLOADING" | "DOWNLOADING" | "TRANSCRIBING" | "ANALYZING"
  | "READY" | "FAILED" | "PAUSED" | "STOPPED";

export type RenderStatus = "NONE" | "QUEUED" | "RUNNING" | "DONE" | "FAILED";
export type LayoutMode = "auto" | "track" | "split" | "wide" | "off";

export interface ProjectDTO {
  id: string;
  sourceType: "youtube" | "upload";
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
  createdAt: string;
  clipCount: number;
  clipsRendered: number;
}

export interface ClipSignals {
  heat?: number | null;
  audio?: number;
  density?: number;
  hook?: number;
  source?: string;
  edges?: string;
  judge?: { hook: number; story: number; value: number; engagement: number; reach: number } | null;
  relevance?: number | null;
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
  title: string;
  description: string;
  hashtags: string;
  templateId: string;
  layoutMode: LayoutMode;
  smartCut: boolean;
  prependBestLine: boolean;
  bestLine: string | null;
  bestLineStart: number | null;
  bestLineEnd: number | null;
  renderStatus: RenderStatus;
  renderError: string | null;
  videoUrl: string | null;
  thumbUrl: string | null;
  downloadUrl: string | null;
  qaWarnings: string[];
  signals: ClipSignals;
  publishStatus: string | null;
  publishInfo: PublishInfo | null;
  tiktokDraft: boolean;
  postedAt: string | null;
  updatedAt: string;
}

export interface CaptionWord {
  i: number;
  w: string;
  start: number;
  end: number;
}

export interface ClipDetail {
  clip: ClipDTO;
  project: ProjectDTO;
  captions: { source: string; edited: boolean; range: [number, number] | null; words: CaptionWord[] };
}

export interface TemplateInfo {
  id: string;
  name: string;
  description: string;
  font: string;
  highlight: string;
  primary: string;
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
  worker?: { alive: boolean; current: { type: string; targetId: string } | null };
  queue?: Record<string, number>;
  publishers?: { name: string; label: string; available: boolean; connected?: boolean }[];
  diskFreeGb?: number;
  error?: string;
}
