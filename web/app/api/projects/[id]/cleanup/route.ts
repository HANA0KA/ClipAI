import type { NextRequest } from "next/server";
import { handleError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";

export async function POST(_req: NextRequest, ctx: RouteContext<"/api/projects/[id]/cleanup">) {
  try {
    const id = safeId((await ctx.params).id);
    return Response.json(await mediaFetch(`/projects/${id}/cleanup`, { method: "POST" }));
  } catch (err) {
    return handleError(err);
  }
}
