import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";

/** Cancela el render en cola o en curso; el MP4 anterior (si lo hay) se conserva. */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]/cancel">) {
  try {
    const id = safeId((await ctx.params).id);
    if (!(await prisma.clip.findUnique({ where: { id }, select: { id: true } }))) return jsonError("Clip no encontrado", 404);
    return Response.json(await mediaFetch<{ status: string }>(`/clips/${id}/cancel-render`, { method: "POST" }));
  } catch (err) {
    return handleError(err);
  }
}
