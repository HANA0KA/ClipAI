import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { projectDir, safeId } from "@/lib/paths";

export const dynamic = "force-dynamic";

const EXT = new Set([".mp4", ".mov", ".m4v", ".mkv", ".webm"]);

/**
 * Recibe el video como cuerpo crudo (PUT, sin multipart) y lo escribe a disco
 * en streaming: un archivo de varios GB nunca pasa entero por memoria.
 */
export async function PUT(req: NextRequest, ctx: RouteContext<"/api/projects/[id]/upload">) {
  try {
    const id = safeId((await ctx.params).id);
    const project = await prisma.project.findUnique({ where: { id } });
    if (!project) return jsonError("Proyecto no encontrado", 404);
    if (project.sourceType !== "upload" || project.status !== "UPLOADING") {
      return jsonError("Este proyecto no espera un archivo", 409);
    }
    const name = req.nextUrl.searchParams.get("name") ?? "video.mp4";
    const ext = path.extname(name).toLowerCase();
    if (!EXT.has(ext)) return jsonError("Formato no admitido");
    if (!req.body) return jsonError("Cuerpo vacío");

    const dir = projectDir(id);
    await fsp.mkdir(dir, { recursive: true });
    const tmp = path.join(dir, `upload.part`);
    await pipeline(Readable.fromWeb(req.body as import("node:stream/web").ReadableStream), fs.createWriteStream(tmp));
    const size = (await fsp.stat(tmp)).size;
    if (size < 10_000) {
      await fsp.unlink(tmp);
      return jsonError("El archivo llegó vacío o incompleto");
    }
    await fsp.rename(tmp, path.join(dir, `upload${ext}`));
    await prisma.project.update({ where: { id }, data: { status: "QUEUED", stage: "En cola" } });
    await enqueueJob("download", id);
    return Response.json({ ok: true, bytes: size });
  } catch (err) {
    return handleError(err);
  }
}
