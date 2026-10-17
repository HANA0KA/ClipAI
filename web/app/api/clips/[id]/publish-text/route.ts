import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import type { PublishText } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * Título, descripción y hashtags para publicar el clip, con el creador del video original (media
 * /clips/<id>/publish-text). Recibe el gancho y los hashtags que se están editando, aunque no se hayan guardado.
 */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/clips/[id]/publish-text">) {
  try {
    const id = safeId((await ctx.params).id);
    if (!(await prisma.clip.findUnique({ where: { id }, select: { id: true } }))) return jsonError("Clip no encontrado", 404);
    const body = (await req.json().catch(() => ({}))) as { hook?: unknown; hashtags?: unknown };
    const pick = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : undefined);
    return Response.json(await mediaFetch<PublishText>(`/clips/${id}/publish-text`, {
      method: "POST",
      json: { hook: pick(body.hook, 300), hashtags: pick(body.hashtags, 600) },
      signal: AbortSignal.timeout(20_000),
    }));
  } catch (err) {
    return handleError(err);
  }
}
