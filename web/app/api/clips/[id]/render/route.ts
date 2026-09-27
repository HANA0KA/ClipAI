import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { safeId } from "@/lib/paths";

/** Encola el render del clip (usa la versión guardada más reciente). */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]/render">) {
  try {
    const id = safeId((await ctx.params).id);
    if (!(await prisma.clip.findUnique({ where: { id }, select: { id: true } }))) return jsonError("Clip no encontrado", 404);
    return Response.json(await enqueueJob("render", id));
  } catch (err) {
    return handleError(err);
  }
}
