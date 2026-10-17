import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { applyGlossary, type GlossaryRule } from "@/lib/glossary";
import { readGlossary } from "@/lib/glossary-store";
import { clipDir, projectDir } from "@/lib/paths";

export interface RawWord {
  w: string;
  start: number;
  end: number;
  hl?: boolean; // destacada a mano (color de énfasis de la plantilla)
}

export interface CaptionsFile {
  source: string;
  range: [number, number] | null;
  edited: boolean;
  words: RawWord[];
}

export interface WordEdit {
  t: number; // inicio de la palabra (identidad estable aunque cambien los bordes)
  w?: string;
  hl?: boolean;
}

const MARGIN = 2;

function withGlossary(words: RawWord[], rules: GlossaryRule[]): RawWord[] {
  if (!rules.length || !words.length) return words;
  const { texts } = applyGlossary(words, rules);
  return words.map((w, i) => (texts[i] === w.w ? w : { ...w, w: texts[i] }));
}

export async function readJson<T>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as T;
  } catch {
    return null;
  }
}

/** Escritura atómica (tmp + rename), igual que media/services/atomic.py. */
export async function writeJsonAtomic(file: string, data: unknown) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2, 6)}.tmp`;
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

export const wordKey = (t: number) => Math.round(t * 1000);

/**
 * Si los tramos salen de lo ya pulido con Whisper, completa con las palabras
 * de transcript.json (calidad de YouTube) para no dejar huecos sin texto.
 */
export async function extendCaptions(projectId: string, clipId: string, ranges: [number, number][]) {
  let caps = await readCaptions(projectId, clipId);
  let transcript: { words: RawWord[] } | null | undefined;
  let rules: GlossaryRule[] | undefined;
  let changed = false;
  for (const [start, end] of ranges) {
    const lo = Math.max(0, start - MARGIN);
    const hi = end + MARGIN;
    const [r0, r1] = caps.range ?? [Infinity, -Infinity];
    if (caps.range && lo >= r0 && hi <= r1) continue;
    if (transcript === undefined) {
      transcript = await readJson<{ words: RawWord[] }>(path.join(projectDir(projectId), "transcript.json"));
    }
    rules ??= await readGlossary(); // las palabras nuevas del transcript también llevan el glosario
    const have = new Set(caps.words.map((w) => wordKey(w.start)));
    const extra = (transcript?.words ?? []).filter((w) => {
      const mid = (w.start + w.end) / 2;
      return mid >= lo && mid < hi && !(mid >= r0 && mid < r1) && !have.has(wordKey(w.start));
    });
    caps = {
      ...caps,
      range: [Math.min(lo, r0), Math.max(hi, r1)],
      words: [...caps.words, ...withGlossary(extra.map((w) => ({ w: w.w, start: w.start, end: w.end })), rules)]
        .sort((a, b) => a.start - b.start),
    };
    changed = true;
  }
  if (changed) await writeJsonAtomic(captionsPath(projectId, clipId), caps);
  return caps;
}

/**
 * Correcciones de texto y destacados. Una palabra vaciada se conserva con
 * texto "" (no se quema) para que «Restaurar original» pueda recuperarla.
 */
export async function applyWordEdits(projectId: string, clipId: string, edits: WordEdit[]) {
  if (!edits.length) return null;
  const caps = await readCaptions(projectId, clipId);
  const byKey = new Map(caps.words.map((w, i) => [wordKey(w.start), i]));
  let changed = false;
  for (const e of edits) {
    const i = byKey.get(wordKey(Number(e.t)));
    if (i === undefined) continue;
    const cur = caps.words[i];
    const next: RawWord = { ...cur };
    if (e.w !== undefined) next.w = String(e.w).replace(/\s+/g, " ").trim().slice(0, 60);
    if (e.hl !== undefined) {
      if (e.hl) next.hl = true;
      else delete next.hl;
    }
    if (next.w !== cur.w || !!next.hl !== !!cur.hl) {
      caps.words[i] = next;
      changed = true;
    }
  }
  if (!changed) return caps;
  caps.edited = true;
  await writeJsonAtomic(captionsPath(projectId, clipId), caps);
  return caps;
}
