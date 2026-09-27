import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import { clipDTO, projectDTO } from "@/lib/serialize";

export const dynamic = "force-dynamic";

export async function GET(_req: NextRequest, ctx: RouteContext<"/api/projects/[id]">) {
  try {
    const id = safeId((await ctx.params).id);
    const project = await prisma.project.findUnique({
      where: { id },
      include: { clips: { orderBy: [{ rank: "asc" }, { score: "desc" }] } },
    });
    if (!project) return jsonError("Proyecto no encontrado", 404);
    return Response.json({ project: projectDTO(project, project.clips), clips: project.clips.map(clipDTO) });
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
