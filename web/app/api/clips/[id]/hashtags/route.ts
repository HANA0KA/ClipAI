import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import type { HashtagSets } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Vuelve a sugerir los hashtags por red con el contenido actual del clip. */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]/hashtags">) {
  try {
    const id = safeId((await ctx.params).id);
    if (!(await prisma.clip.findUnique({ where: { id }, select: { id: true } }))) return jsonError("Clip no encontrado", 404);
    const sets = await mediaFetch<HashtagSets & { source: string }>(`/clips/${id}/hashtags`, {
      method: "POST",
      signal: AbortSignal.timeout(120_000),
    });
    return Response.json(sets);
  } catch (err) {
    return handleError(err);
  }
}
