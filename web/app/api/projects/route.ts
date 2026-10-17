import fs from "node:fs/promises";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { projectDir } from "@/lib/paths";
import { projectDTO } from "@/lib/serialize";
import { validTemplate } from "@/lib/templates";
import { parseSource } from "@/lib/sources";

export const dynamic = "force-dynamic";

const VIDEO_EXT = /\.(mp4|mov|m4v|mkv|webm)$/i;

export async function GET() {
  try {
    const projects = await prisma.project.findMany({
      orderBy: { createdAt: "desc" },
      include: { clips: { select: { renderStatus: true } } },
    });
    return Response.json(projects.map((p) => projectDTO(p, p.clips)));
  } catch (err) {
    return handleError(err);
  }
}

/**
 * Crea un proyecto.
 *  - YouTube o Kick: { url, query?, templateId?, start?, end? } → crea y encola la descarga en
 *    FastAPI. De Kick solo VODs (kick.com/canal/videos/…); ``start``/``end`` (segundos) bajan solo
 *    ese tramo: los directos duran 5–8 h y ClipAI procesa hasta MAX_VIDEO_MINUTES.
 *  - Archivo: { sourceType: "upload", fileName, query?, templateId? } → queda en
 *    UPLOADING hasta que el navegador sube el archivo a /api/projects/:id/upload.
 * ``templateId``: estilo de subtítulos de todos sus clips; sin él, uno
 * automático distinto al de los últimos proyectos (media/services/subtitle_style.py).
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      url?: string; query?: string; sourceType?: string; fileName?: string; templateId?: string | null;
      start?: number | null; end?: number | null;
    };
    const query = body.query?.trim().slice(0, 200) || null;
    const templateId = body.templateId ? await validTemplate(body.templateId) : null;
    if (body.templateId && !templateId) return jsonError("Plantilla de subtítulos inválida");

    if (body.sourceType === "upload") {
      const fileName = String(body.fileName ?? "").trim();
      if (!VIDEO_EXT.test(fileName)) return jsonError("Sube un video MP4, MOV, M4V, MKV o WebM.");
      const project = await prisma.project.create({
        data: {
          sourceType: "upload",
          title: fileName.replace(VIDEO_EXT, "").slice(0, 200),
          folder: "",
          status: "UPLOADING",
          stage: "Esperando el archivo",
          query,
          templateId,
        },
      });
      await fs.mkdir(projectDir(project.id), { recursive: true });
      const updated = await prisma.project.update({
        where: { id: project.id },
        data: { folder: `projects/${project.id}/` },
      });
      return Response.json(projectDTO(updated), { status: 201 });
    }

    const url = String(body.url ?? "").trim();
    const src = parseSource(url);
    if (!src) {
      return jsonError("Pega el enlace de un video de YouTube (youtube.com/watch?v=…, youtu.be o /shorts) o de un VOD de "
        + "Kick (kick.com/canal/videos/…); listas, canales y búsquedas no sirven.");
    }
    if (src.kind !== "video") {
      return jsonError(src.kind === "clip"
        ? "Ese enlace es un clip de Kick (dura menos de un minuto). Pega el VOD: kick.com/canal/videos/…"
        : src.type === "youtube"
          ? "Ese enlace es un canal de YouTube. Elige uno de sus videos (youtube.com/watch?v=…)."
          : "Ese enlace es un canal de Kick. Elige uno de sus VODs (kick.com/canal/videos/…).");
    }
    // El tramo solo tiene sentido en Kick: en YouTube los subtítulos y el mapa de repeticiones cuentan desde el inicio.
    const hasRange = body.start != null || body.end != null;
    if (hasRange && src.type !== "kick") return jsonError("Elegir un tramo solo funciona con VODs de Kick.");
    let range: { rangeStartSec: number; rangeEndSec: number } | null = null;
    if (hasRange) {
      const a = Number(body.start ?? 0);
      const b = Number(body.end);
      if (!Number.isFinite(a) || !Number.isFinite(b) || a < 0 || b <= a) return jsonError("El fin del tramo debe quedar después del inicio.");
      if (b - a < 60) return jsonError("El tramo debe durar al menos 60 s (lo mínimo de un clip).");
      range = { rangeStartSec: Math.floor(a), rangeEndSec: Math.floor(b) };
    }
    const project = await prisma.project.create({
      data: { sourceType: src.type, sourceUrl: url, folder: "", status: "QUEUED", stage: "En cola", query, templateId, ...range },
    });
    await fs.mkdir(projectDir(project.id), { recursive: true });
    await prisma.project.update({ where: { id: project.id }, data: { folder: `projects/${project.id}/` } });
    try {
      await enqueueJob("download", project.id);
    } catch (err) {
      await prisma.project.update({
        where: { id: project.id },
        data: { stage: "El servicio de procesamiento no respondió; pulsa Reintentar cuando esté activo." },
      });
      return handleError(err);
    }
    const fresh = await prisma.project.findUniqueOrThrow({ where: { id: project.id } });
    return Response.json(projectDTO(fresh), { status: 201 });
  } catch (err) {
    return handleError(err);
  }
}
