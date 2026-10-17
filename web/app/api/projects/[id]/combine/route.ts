import path from "node:path";
import type { NextRequest } from "next/server";
import { captionsPath, readCaptions, type RawWord, wordKey, writeJsonAtomic } from "@/lib/captions";
import { originalFromClip } from "@/lib/clip-store";
import { prisma } from "@/lib/db";
import { newSegmentId, type Segment, validateSegments } from "@/lib/edit-doc";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { clipDir, DATA_DIR, safeId } from "@/lib/paths";
import { clipDoc } from "@/lib/serialize";

export const dynamic = "force-dynamic";

/**
 * Combina varios clips en uno NUEVO: sus tramos van seguidos en el orden en
 * que los elegiste. El primero aporta plantilla, encuadre, efectos, audio y
 * textos. Los clips de origen no se tocan.
 */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/projects/[id]/combine">) {
  try {
    const projectId = safeId((await ctx.params).id);
    const { clipIds } = (await req.json().catch(() => ({}))) as { clipIds?: unknown };
    if (!Array.isArray(clipIds) || clipIds.length < 2 || clipIds.length > 10) {
      return jsonError("Elige de 2 a 10 clips para combinar.");
    }
    const ids = clipIds.map((x) => safeId(String(x)));
    if (new Set(ids).size !== ids.length) return jsonError("Hay clips repetidos en la selección.");
    const project = await prisma.project.findUnique({ where: { id: projectId }, include: { clips: true } });
    if (!project) return jsonError("Proyecto no encontrado", 404);
    if (project.sourceDeleted) return jsonError("El video fuente se borró con «Limpiar»: no se puede combinar.", 409);
    const byId = new Map(project.clips.map((c) => [c.id, c]));
    const chosen = ids.map((cid) => byId.get(cid));
    if (chosen.some((c) => !c)) return jsonError("Algún clip no pertenece a este proyecto.");
    const clips = chosen as NonNullable<(typeof chosen)[number]>[];

    const docs = clips.map((c) => clipDoc(c));
    const segments: Segment[] = docs.flatMap((d) => d.segments.map((s) => ({ ...s, id: newSegmentId() })));
    const problem = validateSegments(segments, project.durationSec);
    if (problem) return jsonError(problem);

    // Palabras de cada clip dentro de sus tramos (con sus correcciones y destacados).
    const words = new Map<number, RawWord>();
    for (let k = 0; k < clips.length; k++) {
      const caps = await readCaptions(projectId, clips[k].id);
      for (const w of caps.words) {
        const mid = (w.start + w.end) / 2;
        if (docs[k].segments.some((s) => mid >= s.start - 0.5 && mid < s.end + 0.5) && !words.has(wordKey(w.start))) {
          words.set(wordKey(w.start), w);
        }
      }
    }
    const sorted = [...words.values()].sort((a, b) => a.start - b.start);
    const first = clips[0];
    const doc = { ...docs[0], segments };
    const start = Math.min(...segments.map((s) => s.start));
    const end = Math.max(...segments.map((s) => s.end));
    const created = await prisma.clip.create({
      data: {
        projectId,
        rank: Math.max(...project.clips.map((c) => c.rank)) + 1,
        startSec: start,
        endSec: end,
        score: Math.max(...clips.map((c) => c.score)),
        reason: `Combinación de ${clips.length} clips: ${clips.map((c) => `«${c.hook || c.title}»`).join(", ")}`.slice(0, 500),
        hook: first.hook,
        hookType: first.hookType,
        title: first.title,
        description: first.description,
        hashtags: first.hashtags,
        templateId: first.templateId,
        layoutMode: first.layoutMode,
        smartCut: first.smartCut,
        topic: first.topic,
        edit: JSON.stringify(doc),
        renderStatus: "QUEUED",
      },
    });
    const range: [number, number] = [Math.max(0, start - 2), end + 2];
    const caps = { source: "combined", range, edited: false, words: sorted };
    await writeJsonAtomic(captionsPath(projectId, created.id), caps);
    await writeJsonAtomic(path.join(clipDir(projectId, created.id), "original.json"), {
      version: 1, ...originalFromClip(created, caps), segments,
    });
    const rel = path.relative(DATA_DIR, captionsPath(projectId, created.id)).split(path.sep).join("/");
    await prisma.clip.update({ where: { id: created.id }, data: { captionsPath: rel } });
    try {
      await enqueueJob("render", created.id);
    } catch (err) {
      await prisma.clip.update({ where: { id: created.id }, data: { renderStatus: "NONE" } });
      return handleError(err);
    }
    return Response.json({ id: created.id }, { status: 201 });
  } catch (err) {
    return handleError(err);
  }
}
