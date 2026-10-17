import "server-only";
import path from "node:path";
import { type CaptionsFile, readCaptions, readJson, writeJsonAtomic } from "@/lib/captions";
import { legacySegments } from "@/lib/edit-doc";
import type { Clip } from "@/lib/generated/prisma/client";
import { clipDir } from "@/lib/paths";
import type { LayoutMode, OriginalSnapshot } from "@/lib/types";

// Escrituras de un mismo clip, de una en una dentro del proceso: la revisión
// en la BD ya evita pisadas entre pestañas; esto ordena captions.json.
const locks = new Map<string, Promise<unknown>>();

export async function withClipLock<T>(clipId: string, fn: () => Promise<T>): Promise<T> {
  const prev = locks.get(clipId) ?? Promise.resolve();
  const run = prev.catch(() => undefined).then(fn);
  locks.set(clipId, run);
  try {
    return await run;
  } finally {
    if (locks.get(clipId) === run) locks.delete(clipId);
  }
}

/** Misma forma que media/services/edit_doc.py `original_snapshot`. */
export function originalFromClip(c: Clip, caps: CaptionsFile): OriginalSnapshot {
  return {
    hook: c.hook,
    title: c.title,
    description: c.description,
    hashtags: c.hashtags,
    templateId: c.templateId,
    layoutMode: c.layoutMode as LayoutMode,
    smartCut: c.smartCut,
    segments: legacySegments(c),
    words: caps.words.map((w) => ({ t: Math.round(w.start * 1000) / 1000, w: w.w, hl: !!w.hl })),
  };
}

/** original.json del clip; si no existe (clips de antes del estudio) se crea ahora. */
export async function ensureOriginal(c: Clip): Promise<OriginalSnapshot> {
  const file = path.join(clipDir(c.projectId, c.id), "original.json");
  const saved = await readJson<OriginalSnapshot>(file);
  if (saved && Array.isArray(saved.segments) && Array.isArray(saved.words)) return saved;
  const snapshot = originalFromClip(c, await readCaptions(c.projectId, c.id));
  await writeJsonAtomic(file, { version: 1, ...snapshot });
  return snapshot;
}

