import type { NextRequest } from "next/server";
import { captionsPath, readCaptions, writeJsonAtomic } from "@/lib/captions";
import { withClipLock } from "@/lib/clip-store";
import { prisma } from "@/lib/db";
import { clipDoc } from "@/lib/serialize";
import { gapCandidates } from "@/lib/gapfill";
import { applyGlossary } from "@/lib/glossary";
import { readGlossary } from "@/lib/glossary-store";
import { handleError, jsonError } from "@/lib/http";
import { safeId } from "@/lib/paths";
import { transcriptWords } from "@/lib/transcript-store";

export const dynamic = "force-dynamic";

/**
 * Completa el texto del clip con las palabras que el pulido con Whisper se
 * saltó (las de la transcripción completa dentro de los tramos), con el
 * glosario de correcciones aplicado. Sube la revisión del clip: hay que
 * renderizar de nuevo para verlas en el video.
 */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]/captions">) {
  try {
    const id = safeId((await ctx.params).id);
    return await withClipLock(id, async () => {
      const clip = await prisma.clip.findUnique({ where: { id } });
      if (!clip) return jsonError("Clip no encontrado", 404);
      const caps = await readCaptions(clip.projectId, id);
      const ranges = clipDoc(clip).segments.map((s) => [s.start, s.end] as [number, number]);
      const extra = gapCandidates(caps.words, await transcriptWords(clip.projectId), ranges);
      if (!extra.length) return Response.json({ added: 0 });
      const { texts } = applyGlossary(extra, await readGlossary());
      caps.words = [...caps.words, ...extra.map((w, i) => ({ w: texts[i], start: w.start, end: w.end }))]
        .sort((a, b) => a.start - b.start);
      caps.edited = true;
      await writeJsonAtomic(captionsPath(clip.projectId, id), caps);
      await prisma.clip.update({ where: { id }, data: { editRevision: { increment: 1 } } });
      return Response.json({ added: extra.length });
    });
  } catch (err) {
    return handleError(err);
  }
}
