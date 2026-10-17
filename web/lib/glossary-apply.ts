import "server-only";
import { readCaptions, writeJsonAtomic, captionsPath } from "@/lib/captions";
import { withClipLock } from "@/lib/clip-store";
import { prisma } from "@/lib/db";
import { applyGlossary, type GlossaryRule } from "@/lib/glossary";

/**
 * Aplica reglas a los subtítulos ya guardados de todos los clips (menos
 * ``exceptClipId``: el que se está editando lo corrige su borrador). Un clip
 * cambiado sube su revisión: aparece «Cambios sin renderizar» y un estudio
 * abierto con cambios sin guardar avisa en vez de pisarlos.
 */
export async function applyRulesToAllClips(rules: GlossaryRule[], exceptClipId?: string) {
  const clips = await prisma.clip.findMany({ select: { id: true, projectId: true } });
  let clipsChanged = 0;
  let wordsChanged = 0;
  for (const c of clips) {
    if (c.id === exceptClipId) continue;
    await withClipLock(c.id, async () => {
      const caps = await readCaptions(c.projectId, c.id);
      if (!caps.words.length) return;
      const { texts, changed } = applyGlossary(caps.words, rules);
      if (!changed.length) return;
      changed.forEach((i) => {
        caps.words[i] = { ...caps.words[i], w: texts[i] };
      });
      caps.edited = true;
      await writeJsonAtomic(captionsPath(c.projectId, c.id), caps);
      await prisma.clip.update({ where: { id: c.id }, data: { editRevision: { increment: 1 } } });
      clipsChanged++;
      wordsChanged += changed.length;
    });
  }
  return { clips: clipsChanged, words: wordsChanged };
}
