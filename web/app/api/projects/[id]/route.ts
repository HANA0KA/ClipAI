import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import { clipDTO, clipOrder, projectDTO } from "@/lib/serialize";
import { validTemplate } from "@/lib/templates";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: RouteContext<"/api/projects/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    const project = await prisma.project.findUnique({
      where: { id },
      include: { clips: { orderBy: [{ rank: "asc" }, { score: "desc" }] } },
    });
    if (!project) return jsonError("Proyecto no encontrado", 404);
    const order = clipOrder(project.clips);
    return Response.json({
      project: projectDTO(project, project.clips),
      clips: project.clips.map((c) => clipDTO(c, order)),
    });
  } catch (err) {
    return handleError(err);
  }
}

/**
 * Estilo de subtítulos del proyecto: { templateId } lo aplica a TODOS sus
 * clips (luego cada uno se puede cambiar en el estudio). Sube la revisión de
 * cada clip: un estudio abierto con cambios sin guardar avisa en vez de pisarlo.
 */
export async function PATCH(req: NextRequest, ctx: RouteContext<"/api/projects/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    const body = (await req.json().catch(() => ({}))) as { templateId?: unknown };
    const templateId = await validTemplate(body.templateId);
    if (!templateId) return jsonError("Plantilla de subtítulos inválida");
    const exists = await prisma.project.findUnique({ where: { id }, select: { id: true } });
    if (!exists) return jsonError("Proyecto no encontrado", 404);
    const [, changed] = await prisma.$transaction([
      prisma.project.update({ where: { id }, data: { templateId } }),
      prisma.clip.updateMany({
        where: { projectId: id, templateId: { not: templateId } },
        data: { templateId, editRevision: { increment: 1 } },
      }),
    ]);
    return Response.json({ templateId, changed: changed.count });
  } catch (err) {
    return handleError(err);
  }
}

/** Descartar: cancela sus jobs, borra la fila y la carpeta (lo hace FastAPI). */
export async function DELETE(_req: NextRequest, ctx: RouteContext<"/api/projects/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    await mediaFetch(`/projects/${id}/control`, { method: "POST", json: { action: "discard" } });
    return Response.json({ ok: true });
  } catch (err) {
    return handleError(err);
  }
}
