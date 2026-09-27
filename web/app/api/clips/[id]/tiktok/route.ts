import type { NextRequest } from "next/server";
import { handleError } from "@/lib/http";
import { enqueueJob } from "@/lib/media";
import { safeId } from "@/lib/paths";

/** Encola el envío del MP4 a los borradores de TikTok (opcional). */
export async function POST(_req: NextRequest, ctx: RouteContext<"/api/clips/[id]/tiktok">) {
  try {
    const id = safeId((await ctx.params).id);
    return Response.json(await enqueueJob("tiktok_draft", id));
  } catch (err) {
    return handleError(err);
  }
}
