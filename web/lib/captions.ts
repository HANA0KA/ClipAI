import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { clipDir, projectDir } from "@/lib/paths";

export interface RawWord {
  w: string;
  start: number;
  end: number;
}

export interface CaptionsFile {
  source: string;
  range: [number, number] | null;
  edited: boolean;
  words: RawWord[];
}

const MARGIN = 2;

async function readJson<T>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as T;
  } catch {
    return null;
  }
}

/** Escritura atómica (tmp + rename), igual que media/services/atomic.py. */
export async function writeJsonAtomic(file: string, data: unknown) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(data, null, 1), { mode: 0o600 });
  await fs.rename(tmp, file);
}

export function captionsPath(projectId: string, clipId: string) {
  return path.join(clipDir(projectId, clipId), "captions.json");
}

export async function readCaptions(projectId: string, clipId: string): Promise<CaptionsFile> {
  const data = await readJson<CaptionsFile>(captionsPath(projectId, clipId));
  return data ?? { source: "none", range: null, edited: false, words: [] };
}

/**
 * Si los bordes nuevos salen del tramo ya pulido con Whisper, completa con las
 * palabras de transcript.json (calidad de YouTube) para no dejar huecos sin texto.
 */
export async function extendCaptions(projectId: string, clipId: string, start: number, end: number) {
  const caps = await readCaptions(projectId, clipId);
  const lo = Math.max(0, start - MARGIN);
  const hi = end + MARGIN;
  const [r0, r1] = caps.range ?? [Infinity, -Infinity];
  if (caps.range && lo >= r0 && hi <= r1) return caps;
  const transcript = await readJson<{ words: RawWord[] }>(path.join(projectDir(projectId), "transcript.json"));
  const extra = (transcript?.words ?? []).filter((w) => {
    const mid = (w.start + w.end) / 2;
    return mid >= lo && mid < hi && !(mid >= r0 && mid < r1);
  });
  const words = [...caps.words, ...extra].sort((a, b) => a.start - b.start);
  const next: CaptionsFile = {
    ...caps,
    range: [Math.min(lo, r0), Math.max(hi, r1)],
    words,
  };
  await writeJsonAtomic(captionsPath(projectId, clipId), next);
  return next;
}

/** Aplica correcciones de texto por índice (los tiempos no cambian). */
export async function editCaptionWords(projectId: string, clipId: string, edits: { i: number; w: string }[]) {
  const caps = await readCaptions(projectId, clipId);
  for (const e of edits) {
    if (Number.isInteger(e.i) && e.i >= 0 && e.i < caps.words.length) {
      caps.words[e.i] = { ...caps.words[e.i], w: String(e.w).trim().slice(0, 60) };
    }
  }
  caps.words = caps.words.filter((w) => w.w.length > 0);
  caps.edited = true;
  await writeJsonAtomic(captionsPath(projectId, clipId), caps);
  return caps;
}
