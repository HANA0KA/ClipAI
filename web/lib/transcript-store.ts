import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import type { TimedWord } from "@/lib/gapfill";
import { projectDir } from "@/lib/paths";

// transcript.json puede pesar cientos de KB y el estudio consulta el clip cada
// 1,5 s mientras renderiza: se lee una vez y se reutiliza mientras no cambie.
const cache = new Map<string, { mtime: number; words: TimedWord[] }>();

export async function transcriptWords(projectId: string): Promise<TimedWord[]> {
  const file = path.join(projectDir(projectId), "transcript.json");
  try {
    const { mtimeMs } = await fs.stat(file);
    const hit = cache.get(file);
    if (hit && hit.mtime === mtimeMs) return hit.words;
    const words = ((JSON.parse(await fs.readFile(file, "utf8")) as { words?: TimedWord[] }).words ?? [])
      .map((w) => ({ w: String(w.w), start: w.start, end: w.end }));
    if (cache.size >= 4) cache.delete(cache.keys().next().value as string);
    cache.set(file, { mtime: mtimeMs, words });
    return words;
  } catch {
    return [];
  }
}
