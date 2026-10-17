import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import { mediaUrl } from "@/lib/serialize";
import type { TimelineAssets } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Miniaturas y forma de onda del video fuente para la línea de tiempo del estudio. */
export async function GET(req: NextRequest, ctx: RouteContext<"/api/clips/[id]/timeline">) {
  try {
    const id = safeId((await ctx.params).id);
    const start = Number(req.nextUrl.searchParams.get("start"));
    const end = Number(req.nextUrl.searchParams.get("end"));
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) {
      return jsonError("Rango inválido");
    }
    const data = await mediaFetch<TimelineAssets>(
      `/clips/${id}/timeline?start=${start.toFixed(2)}&end=${end.toFixed(2)}`,
      { signal: AbortSignal.timeout(120_000) },
    );
    return Response.json({ ...data, thumbs: mediaUrl(data.thumbs) });
  } catch (err) {
    return handleError(err);
  }
}
