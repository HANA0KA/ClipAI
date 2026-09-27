import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";

const ACTIONS = new Set(["pause", "resume", "stop", "retry", "reanalyze"]);

/** Pausar, reanudar, detener conservando lo hecho, reintentar o volver a analizar. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/projects/[id]/control">) {
  try {
    const id = safeId((await ctx.params).id);
    const { action } = (await req.json().catch(() => ({}))) as { action?: string };
    if (!action || !ACTIONS.has(action)) return jsonError("Acción no válida");
    return Response.json(await mediaFetch(`/projects/${id}/control`, { method: "POST", json: { action } }));
  } catch (err) {
    return handleError(err);
  }
}
