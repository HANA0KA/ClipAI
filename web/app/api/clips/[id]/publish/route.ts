import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { safeId } from "@/lib/paths";

const PLATFORMS = new Set(["youtube", "tiktok", "instagram"]);

/** Publica vía intermediario (Upload-Post). Si hay tope diario, queda para mañana. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/clips/[id]/publish">) {
  try {
    const id = safeId((await ctx.params).id);
    const body = (await req.json().catch(() => ({}))) as { platforms?: string[]; when?: string };
    const platforms = (body.platforms ?? ["youtube"]).filter((p) => PLATFORMS.has(p));
    if (!platforms.length) return jsonError("Elige al menos una plataforma");
    return Response.json(await enqueueJob("publish", id, { provider: "upload_post", platforms, when: body.when ?? null }));
  } catch (err) {
    return handleError(err);
  }
}
