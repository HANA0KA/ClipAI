import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";

/** Borra una fuente subida (las incluidas no se pueden borrar). */
export async function DELETE(_req: NextRequest, ctx: RouteContext<"/api/fonts/[file]">) {
  try {
    const file = (await ctx.params).file;
    if (!/^user-[\w-]+\.(ttf|otf)$/i.test(file)) return jsonError("Solo se pueden borrar las fuentes que subiste.");
    return Response.json(await mediaFetch(`/fonts/${encodeURIComponent(file)}`, { method: "DELETE" }));
  } catch (err) {
    return handleError(err);
  }
}
