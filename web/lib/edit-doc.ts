// Documento de edición del clip (estudio). Misma forma y mismos límites que
// media/services/edit_doc.py, que es quien lo lee al renderizar.

export type Aspect = "vertical" | "square" | "original";
export type Fit = "cover" | "contain";
export type Preset = "tiktok" | "reels" | "shorts";

export interface Segment {
  id: string;
  start: number; // segundos del video fuente
  end: number;
}

export interface Framing {
  mode: "auto" | "manual";
  aspect: Aspect;
  fit: Fit;
  zoom: number; // 1–3
  x: number; // 0–1, ancla horizontal
  y: number; // 0–1, ancla vertical
}

export interface Effects {
  brightness: number; // 40–180 (%)
  contrast: number; // 40–180 (%)
  saturation: number; // 0–220 (%)
  blur: number; // 0–8 (px a 1080 de ancho)
  hue: number; // −180–180 (grados)
}

export interface AudioSettings {
  volume: number; // 0–2
  muted: boolean;
}

export interface EditDoc {
  version: 1;
  segments: Segment[];
  framing: Framing;
  effects: Effects;
  audio: AudioSettings;
  preset: Preset;
  font: string | null;
  punch: boolean; // acercamientos en las palabras fuertes
  hookSeconds: number | null; // gancho en pantalla: null = automático (1,5–8 s)
}

export const MAX_SEGMENTS = 20;
export const MIN_SEGMENT = 0.2;
export const MAX_CLIP_SECONDS = 180;
export const BEST_LINE_ID = "best";

export const DEFAULT_FRAMING: Framing = { mode: "auto", aspect: "vertical", fit: "cover", zoom: 1, x: 0.5, y: 0.5 };
export const DEFAULT_EFFECTS: Effects = { brightness: 100, contrast: 100, saturation: 100, blur: 0, hue: 0 };
export const DEFAULT_AUDIO: AudioSettings = { volume: 1, muted: false };

export const EFFECT_LIMITS: Record<keyof Effects, [number, number]> = {
  brightness: [40, 180],
  contrast: [40, 180],
  saturation: [0, 220],
  blur: [0, 8],
  hue: [-180, 180],
};

export const PRESETS: { id: Preset; label: string; maxrate: string }[] = [
  { id: "tiktok", label: "TikTok", maxrate: "10 Mb/s" },
  { id: "reels", label: "Reels", maxrate: "12 Mb/s" },
  { id: "shorts", label: "Shorts", maxrate: "10 Mb/s" },
];

const clamp = (v: unknown, lo: number, hi: number, dflt: number) => {
  const x = typeof v === "number" ? v : Number(v);
  return Number.isFinite(x) ? Math.min(hi, Math.max(lo, x)) : dflt;
};
const round3 = (x: number) => Math.round(x * 1000) / 1000;

export function newSegmentId(): string {
  return `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

/** Bordes de siempre (antes del estudio): frase más fuerte delante si está activada. */
export function legacySegments(c: {
  startSec: number; endSec: number; prependBestLine: boolean; bestLineStart: number | null; bestLineEnd: number | null;
}): Segment[] {
  const out: Segment[] = [];
  if (c.prependBestLine && c.bestLineStart != null && c.bestLineEnd != null) {
    out.push({ id: BEST_LINE_ID, start: c.bestLineStart, end: c.bestLineEnd });
  }
  out.push({ id: "s1", start: c.startSec, end: c.endSec });
  return out;
}

function parseRaw(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object") return raw as Record<string, unknown>;
  if (typeof raw === "string" && raw.trim()) {
    try {
      const v = JSON.parse(raw);
      return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return {};
}

export function normalizeSegments(raw: unknown): Segment[] {
  if (!Array.isArray(raw)) return [];
  const out: Segment[] = [];
  const ids = new Set<string>();
  for (const s of raw.slice(0, MAX_SEGMENTS)) {
    if (!s || typeof s !== "object") continue;
    const r = s as Record<string, unknown>;
    const start = clamp(r.start, 0, 1e7, -1);
    const end = clamp(r.end, 0, 1e7, -1);
    if (start < 0 || end - start < MIN_SEGMENT) continue;
    let id = typeof r.id === "string" && /^[\w-]{1,40}$/.test(r.id) ? r.id : newSegmentId();
    if (ids.has(id)) id = newSegmentId();
    ids.add(id);
    out.push({ id, start: round3(start), end: round3(end) });
  }
  return out;
}

/** JSON de la columna Clip.edit → documento completo y dentro de rango. */
export function normalizeDoc(raw: unknown, fallbackSegments: Segment[]): EditDoc {
  const d = parseRaw(raw);
  const f = parseRaw(d.framing);
  const fx = parseRaw(d.effects);
  const au = parseRaw(d.audio);
  const segments = normalizeSegments(d.segments);
  const font = typeof d.font === "string" && d.font.trim() && d.font.length <= 80 && !d.font.includes(",")
    ? d.font.trim() : null;
  return {
    version: 1,
    segments: segments.length ? segments : fallbackSegments,
    framing: {
      mode: f.mode === "manual" ? "manual" : "auto",
      aspect: f.aspect === "square" || f.aspect === "original" ? f.aspect : "vertical",
      fit: f.fit === "contain" ? "contain" : "cover",
      zoom: clamp(f.zoom, 1, 3, 1),
      x: clamp(f.x, 0, 1, 0.5),
      y: clamp(f.y, 0, 1, 0.5),
    },
    effects: Object.fromEntries(
      (Object.keys(EFFECT_LIMITS) as (keyof Effects)[]).map((k) => [
        k, clamp(fx[k], EFFECT_LIMITS[k][0], EFFECT_LIMITS[k][1], DEFAULT_EFFECTS[k]),
      ]),
    ) as unknown as Effects,
    audio: { volume: clamp(au.volume, 0, 2, 1), muted: au.muted === true },
    preset: d.preset === "reels" || d.preset === "shorts" ? d.preset : "tiktok",
    font,
    punch: d.punch !== false,
    hookSeconds: d.hookSeconds == null || d.hookSeconds === "" ? null : clamp(d.hookSeconds, 1.5, 8, 3),
  };
}

export function totalDuration(segments: Segment[]): number {
  return segments.reduce((acc, s) => acc + Math.max(0, s.end - s.start), 0);
}

export function outputSize(aspect: Aspect, sw: number, sh: number): { w: number; h: number } {
  if (aspect === "square") return { w: 1080, h: 1080 };
  if (aspect === "original" && sw > 0 && sh > 0) {
    const k = Math.min(1, 1920 / Math.max(sw, sh));
    return { w: Math.round((sw * k) / 2) * 2, h: Math.round((sh * k) / 2) * 2 };
  }
  return { w: 1080, h: 1920 };
}

/** Misma fórmula que edit_doc.framing_geometry (en cualquier escala). */
export function framingGeometry(sw: number, sh: number, w: number, h: number, f: Framing) {
  const base = (f.fit === "cover" ? Math.max : Math.min)(w / sw, h / sh) * f.zoom;
  const rw = sw * base;
  const rh = sh * base;
  const cw = Math.min(w, rw);
  const ch = Math.min(h, rh);
  return {
    rw, rh, cw, ch,
    cx: (rw - cw) * f.x, cy: (rh - ch) * f.y,
    ox: (w - cw) * f.x, oy: (h - ch) * f.y,
    fills: cw >= w - 0.5 && ch >= h - 0.5,
  };
}

/** Filtro CSS equivalente a los efectos del render (misma matemática). */
export function cssFilter(e: Effects, pxScale: number): string {
  // Solo lo que cambia algo: un filtro neutro obliga igual al navegador a
  // procesar cada cuadro del video (más CPU/GPU sin cambiar la imagen).
  const parts: string[] = [];
  if (e.brightness !== 100) parts.push(`brightness(${e.brightness / 100})`);
  if (e.contrast !== 100) parts.push(`contrast(${e.contrast / 100})`);
  if (e.saturation !== 100) parts.push(`saturate(${e.saturation / 100})`);
  if (e.hue !== 0) parts.push(`hue-rotate(${e.hue}deg)`);
  if (e.blur > 0) parts.push(`blur(${(e.blur * pxScale).toFixed(2)}px)`);
  return parts.join(" ");
}

export function isDefaultEffects(e: Effects): boolean {
  return (Object.keys(DEFAULT_EFFECTS) as (keyof Effects)[]).every((k) => Math.abs(e[k] - DEFAULT_EFFECTS[k]) < 1e-6);
}

/** Segmento que contiene el segundo `t` del video fuente (el primero que coincida). */
export function segmentAt(segments: Segment[], t: number): number {
  return segments.findIndex((s) => t >= s.start - 1e-3 && t < s.end - 1e-3);
}

/** Validación del servidor: devuelve un mensaje en español o null. */
export function validateSegments(segments: Segment[], videoDuration: number | null): string | null {
  if (!segments.length) return "El clip necesita al menos un tramo.";
  if (segments.length > MAX_SEGMENTS) return `Como máximo ${MAX_SEGMENTS} tramos.`;
  const max = videoDuration ?? Infinity;
  for (const s of segments) {
    if (s.start < 0 || s.end > max + 1) return "Un tramo queda fuera del video.";
    if (s.end - s.start < MIN_SEGMENT) return "Cada tramo debe durar al menos 0,2 s.";
  }
  if (totalDuration(segments) > MAX_CLIP_SECONDS) return "Un clip no puede durar más de 3 minutos.";
  return null;
}
