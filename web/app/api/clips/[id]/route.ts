import fs from "node:fs/promises";
import type { NextRequest } from "next/server";
import { applyWordEdits, extendCaptions, readCaptions, type WordEdit } from "@/lib/captions";
import { ensureOriginal, withClipLock } from "@/lib/clip-store";
import { prisma } from "@/lib/db";
import { BEST_LINE_ID, type EditDoc, normalizeDoc, normalizeSegments, validateSegments } from "@/lib/edit-doc";
import type { Prisma } from "@/lib/generated/prisma/client";
import { sanitizeHook } from "@/lib/hook";
import { gapCandidates } from "@/lib/gapfill";
import { handleError, jsonError } from "@/lib/http";
import { transcriptWords } from "@/lib/transcript-store";
import { clipDir, safeId } from "@/lib/paths";
import { clipDoc, clipDTO, clipOrder, projectDTO } from "@/lib/serialize";
import type { CaptionWord, ClipDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

const LAYOUTS = new Set(["auto", "track", "split", "wide", "off"]);
const TEMPLATES = /^[a-z0-9-]{2,40}$/;

async function detail(id: string): Promise<ClipDetail | null> {
  const clip = await prisma.clip.findUnique({
    where: { id },
    include: {
      project: { include: { clips: { select: { id: true, createdAt: true, rank: true, score: true, renderStatus: true } } } },
    },
  });
  if (!clip) return null;
  const doc = clipDoc(clip);
  const [caps, original] = await Promise.all([readCaptions(clip.projectId, clip.id), ensureOriginal(clip)]);
  const lo = Math.min(...doc.segments.map((s) => s.start), ...original.segments.map((s) => s.start)) - 0.5;
  const hi = Math.max(...doc.segments.map((s) => s.end), ...original.segments.map((s) => s.end)) + 0.5;
  const words: CaptionWord[] = caps.words
    .filter((w) => (w.start + w.end) / 2 >= lo && (w.start + w.end) / 2 < hi)
    .map((w) => ({ t: Math.round(w.start * 1000) / 1000, w: w.w, start: w.start, end: w.end, hl: !!w.hl }));
  // Habla que Whisper se saltó y YouTube sí trae (solo si el texto es del pulido con Whisper).
  const missing = caps.source === "whisper"
    ? gapCandidates(caps.words, await transcriptWords(clip.projectId), doc.segments.map((s) => [s.start, s.end])).length
    : 0;
  return {
    clip: clipDTO(clip, clipOrder(clip.project.clips)),
    project: projectDTO(clip.project, clip.project.clips),
    captions: { source: caps.source, edited: caps.edited, range: caps.range, words, missing },
    doc,
    original,
  };
}

export async function GET(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]">) {
  try {
    const d = await detail(safeId((await ctx.params).id));
    return d ? Response.json(d) : jsonError("Clip no encontrado", 404);
  } catch (err) {
    return handleError(err);
  }
}

interface PatchBody {
  revision?: number;
  doc?: Partial<EditDoc>;
  hook?: string;
  hashtags?: string;
  templateId?: string;
  layoutMode?: string;
  smartCut?: boolean;
  posted?: boolean;
  words?: WordEdit[];
}

/**
 * Guarda el borrador del estudio. Con ``revision`` el guardado es condicional:
 * si otra pestaña guardó antes, 409 y no se toca nada. Sin ``revision`` solo
 * se admiten cambios que no forman parte del borrador (marcar como subido).
 */
export async function PATCH(req: NextRequest, ctx: RouteContext<"/api/clips/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    const b = (await req.json().catch(() => ({}))) as PatchBody;
    return await withClipLock(id, async () => {
      const clip = await prisma.clip.findUnique({ where: { id }, include: { project: true } });
      if (!clip) return jsonError("Clip no encontrado", 404);
      const data: Prisma.ClipUpdateManyMutationInput = {};
      if (b.posted !== undefined) data.postedAt = b.posted ? new Date() : null;

      const editing = b.doc !== undefined || b.words !== undefined || ["hook", "hashtags",
        "templateId", "layoutMode", "smartCut"].some((k) => b[k as keyof PatchBody] !== undefined);
      if (editing && !Number.isInteger(b.revision)) {
        return jsonError("Falta la revisión del borrador: recarga el estudio.", 400);
      }

      let ranges: [number, number][] = [];
      if (b.doc !== undefined) {
        const current = clipDoc(clip);
        if (b.doc.segments !== undefined
          && (!Array.isArray(b.doc.segments) || normalizeSegments(b.doc.segments).length !== b.doc.segments.length)) {
          return jsonError("Tramo inválido: cada tramo debe durar al menos 0,2 s y terminar después de empezar.");
        }
        const doc = normalizeDoc({ ...current, ...b.doc }, current.segments);
        const problem = validateSegments(doc.segments, clip.project.durationSec);
        if (problem) return jsonError(problem);
        const sameSegments = JSON.stringify(doc.segments.map((s) => [s.start, s.end]))
          === JSON.stringify(current.segments.map((s) => [s.start, s.end]));
        if (!sameSegments && clip.project.sourceDeleted) {
          return jsonError("El video fuente se borró con «Limpiar»: los tramos ya no se pueden cambiar.", 409);
        }
        data.edit = JSON.stringify(doc);
        data.startSec = Math.min(...doc.segments.map((s) => s.start));
        data.endSec = Math.max(...doc.segments.map((s) => s.end));
        data.prependBestLine = doc.segments.some((s) => s.id === BEST_LINE_ID) && clip.bestLineStart != null;
        ranges = doc.segments.map((s) => [s.start, s.end]);
      }
      if (b.hook !== undefined) {
        // El gancho (con su emoji) es a la vez el título y la descripción del post.
        data.hook = sanitizeHook(b.hook).slice(0, 120);
        data.title = data.hook;
        data.description = "";
      }
      if (b.hashtags !== undefined) data.hashtags = String(b.hashtags).slice(0, 300);
      if (b.templateId !== undefined) {
        if (!TEMPLATES.test(b.templateId)) return jsonError("Plantilla inválida");
        data.templateId = b.templateId;
      }
      if (b.layoutMode !== undefined) {
        if (!LAYOUTS.has(b.layoutMode)) return jsonError("Diseño inválido");
        data.layoutMode = b.layoutMode;
      }
      if (b.smartCut !== undefined) data.smartCut = !!b.smartCut;

      if (editing) {
        const res = await prisma.clip.updateMany({
          where: { id, editRevision: b.revision },
          data: { ...data, editRevision: { increment: 1 } },
        });
        if (res.count === 0) {
          return jsonError("Este clip se editó en otra pestaña. Recarga para ver la última versión.", 409);
        }
      } else if (Object.keys(data).length) {
        await prisma.clip.updateMany({ where: { id }, data });
      }
      // Los archivos solo se tocan después de ganar la revisión en la BD.
      if (ranges.length) await extendCaptions(clip.projectId, clip.id, ranges);
      if (Array.isArray(b.words) && b.words.length) {
        await applyWordEdits(clip.projectId, clip.id, b.words.slice(0, 5000));
      }
      return Response.json(await detail(id));
    });
  } catch (err) {
    return handleError(err);
  }
}

/**
 * Elimina un clip: su fila, sus jobs en cola y su carpeta (video, portada,
 * subtítulos, borrador). No se puede deshacer. Mientras se renderiza o
 * publica hay que cancelarlo o esperar.
 */
export async function DELETE(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    return await withClipLock(id, async () => {
      const clip = await prisma.clip.findUnique({
        where: { id }, select: { projectId: true, renderStatus: true, publishStatus: true },
      });
      if (!clip) return jsonError("Clip no encontrado", 404);
      if (clip.renderStatus === "RUNNING" || clip.publishStatus === "RUNNING") {
        return jsonError("Este clip se está procesando ahora mismo: cancela el render o espera a que termine.", 409);
      }
      await prisma.job.updateMany({ where: { targetId: id, status: "QUEUED" }, data: { status: "CANCELLED" } });
      await prisma.clip.delete({ where: { id } });
      await fs.rm(clipDir(clip.projectId, id), { recursive: true, force: true });
      return Response.json({ ok: true });
    });
  } catch (err) {
    return handleError(err);
  }
}
