import type { NextRequest } from "next/server";
import { editCaptionWords, extendCaptions, readCaptions } from "@/lib/captions";
import { prisma } from "@/lib/db";
import type { Prisma } from "@/lib/generated/prisma/client";
import { handleError, jsonError } from "@/lib/http";
import { safeId } from "@/lib/paths";
import { clipDTO, projectDTO } from "@/lib/serialize";
import type { CaptionWord, ClipDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

const LAYOUTS = new Set(["auto", "track", "split", "wide", "off"]);
const TEMPLATES = /^[a-z0-9-]{2,40}$/;

async function detail(id: string): Promise<ClipDetail | null> {
  const clip = await prisma.clip.findUnique({ where: { id }, include: { project: { include: { clips: { select: { renderStatus: true } } } } } });
  if (!clip) return null;
  const caps = await readCaptions(clip.projectId, clip.id);
  const lo = Math.min(clip.startSec, clip.bestLineStart ?? clip.startSec) - 0.5;
  const hi = clip.endSec + 0.5;
  const words: CaptionWord[] = caps.words
    .map((w, i) => ({ i, w: w.w, start: w.start, end: w.end }))
    .filter((w) => (w.start + w.end) / 2 >= lo && (w.start + w.end) / 2 < hi);
  return {
    clip: clipDTO(clip),
    project: projectDTO(clip.project, clip.project.clips),
    captions: { source: caps.source, edited: caps.edited, range: caps.range, words },
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
  startSec?: number;
  endSec?: number;
  hook?: string;
  title?: string;
  description?: string;
  hashtags?: string;
  templateId?: string;
  layoutMode?: string;
  smartCut?: boolean;
  prependBestLine?: boolean;
  posted?: boolean;
  words?: { i: number; w: string }[];
}

/** Guarda bordes, palabras, gancho, plantilla, diseño y textos del kit. */
export async function PATCH(req: NextRequest, ctx: RouteContext<"/api/clips/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    const clip = await prisma.clip.findUnique({ where: { id }, include: { project: true } });
    if (!clip) return jsonError("Clip no encontrado", 404);
    const b = (await req.json().catch(() => ({}))) as PatchBody;
    const data: Prisma.ClipUpdateInput = {};

    if (b.startSec !== undefined || b.endSec !== undefined) {
      const start = Number(b.startSec ?? clip.startSec);
      const end = Number(b.endSec ?? clip.endSec);
      const max = clip.project.durationSec ?? Infinity;
      if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start + 3 || end > max + 1) {
        return jsonError("Bordes inválidos: el clip debe durar más de 3 s y estar dentro del video.");
      }
      if (end - start > 180) return jsonError("Un clip no puede durar más de 3 minutos.");
      data.startSec = Math.round(start * 1000) / 1000;
      data.endSec = Math.round(end * 1000) / 1000;
      await extendCaptions(clip.projectId, clip.id, start, end);
    }
    if (b.hook !== undefined) data.hook = String(b.hook).slice(0, 120);
    if (b.title !== undefined) data.title = String(b.title).slice(0, 100);
    if (b.description !== undefined) data.description = String(b.description).slice(0, 2000);
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
    if (b.prependBestLine !== undefined) data.prependBestLine = !!b.prependBestLine && clip.bestLineStart != null;
    if (b.posted !== undefined) data.postedAt = b.posted ? new Date() : null;
    if (Array.isArray(b.words) && b.words.length) await editCaptionWords(clip.projectId, clip.id, b.words);

    await prisma.clip.update({ where: { id }, data });
    return Response.json(await detail(id));
  } catch (err) {
    return handleError(err);
  }
}
