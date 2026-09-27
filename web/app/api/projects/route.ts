import fs from "node:fs/promises";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { projectDir } from "@/lib/paths";
import { projectDTO } from "@/lib/serialize";

export const dynamic = "force-dynamic";

const YOUTUBE_RE = /^(https?:\/\/)?(www\.|m\.|music\.)?(youtube\.com\/(watch\?|shorts\/|live\/|embed\/)|youtu\.be\/)/i;
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
 *  - YouTube: { url, query? } → crea y encola la descarga en FastAPI.
 *  - Archivo: { sourceType: "upload", fileName, query? } → queda en UPLOADING
 *    hasta que el navegador sube el archivo a /api/projects/:id/upload.
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as {
      url?: string; query?: string; sourceType?: string; fileName?: string;
    };
    const query = body.query?.trim().slice(0, 200) || null;

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
    if (!YOUTUBE_RE.test(url)) return jsonError("Pega un enlace de YouTube (youtube.com/watch, youtu.be o /shorts).");
    const project = await prisma.project.create({
      data: { sourceType: "youtube", sourceUrl: url, folder: "", status: "QUEUED", stage: "En cola", query },
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
