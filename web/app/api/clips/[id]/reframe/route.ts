import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { safeId } from "@/lib/paths";

const MODES = new Set(["auto", "track", "split", "wide", "off"]);

/** Cambia el diseño de encuadre y re-renderiza desde el trozo 16:9 guardado. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/clips/[id]/reframe">) {
  try {
    const id = safeId((await ctx.params).id);
    const { mode } = (await req.json().catch(() => ({}))) as { mode?: string };
    if (!mode || !MODES.has(mode)) return jsonError("Diseño inválido: auto, track, split, wide u off.");
    await prisma.clip.update({ where: { id }, data: { layoutMode: mode } });
    return Response.json(await enqueueJob("render", id));
  } catch (err) {
    return handleError(err);
  }
}
