/** 83.4 → "1:23" ; con décimas → "1:23.4" */
export function timecode(sec: number | null | undefined, decimals = false): string {
  if (sec == null || !Number.isFinite(sec)) return "–";
  const neg = sec < 0;
  const s = Math.abs(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = s % 60;
  const secStr = decimals ? rest.toFixed(1).padStart(4, "0") : String(Math.floor(rest)).padStart(2, "0");
  const body = h > 0 ? `${h}:${String(m).padStart(2, "0")}:${secStr}` : `${m}:${secStr}`;
  return neg ? `-${body}` : body;
}

/** Duración legible: 45 → "45 s", 754 → "12 min" */
export function duration(sec: number | null | undefined): string {
  if (sec == null) return "–";
  if (sec < 90) return `${Math.round(sec)} s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return `${h} h ${m} min`;
}

export function relativeDate(iso: string): string {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return d.toLocaleDateString("es", { day: "numeric", month: "short" });
}

export const STATUS_LABEL: Record<string, string> = {
  QUEUED: "En cola",
  UPLOADING: "Subiendo",
  DOWNLOADING: "Descargando",
  TRANSCRIBING: "Transcribiendo",
  ANALYZING: "Buscando momentos",
  READY: "Listo",
  FAILED: "Falló",
  PAUSED: "En pausa",
  STOPPED: "Detenido",
};

export const ACTIVE_STATUSES = ["QUEUED", "UPLOADING", "DOWNLOADING", "TRANSCRIBING", "ANALYZING"];

export const TRANSCRIPT_LABEL: Record<string, string> = {
  "youtube-manual": "subtítulos del creador",
  "youtube-auto": "subtítulos automáticos",
  "transcript-api": "subtítulos (respaldo)",
  whisper: "Whisper",
};

export function llmLabel(provider: string | null | undefined): string {
  if (!provider) return "";
  if (provider === "heuristic") return "sin IA (señales)";
  const [kind, model] = provider.split(":");
  if (kind === "gemini") return model;
  if (kind === "vertex") return `${model} (Vertex)`;
  return kind === "openai" ? `local: ${model}` : provider;
}

/** Costo de IA del proyecto: «≈ US$0,012 · 38 mil tokens». */
export function aiUsage(usd: number, tokens: number, estimated: boolean, provider: string | null): string {
  const k = tokens >= 1_000_000 ? `${(tokens / 1_000_000).toFixed(1)} M` : `${Math.max(1, Math.round(tokens / 1000))} mil`;
  if (provider?.startsWith("openai:") && usd === 0) return `IA local · ${k} tokens`;
  const money = usd < 0.01 ? usd.toFixed(4) : usd.toFixed(3);
  return `IA ${estimated ? "≈ " : ""}US$${money.replace(".", ",")} · ${k} tokens`;
}

