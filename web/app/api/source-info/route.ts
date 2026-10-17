import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { parseSource } from "@/lib/sources";
import type { SourceInfo } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * Comprueba el enlace de un nuevo proyecto antes de crearlo (media /source-info):
 * de un VOD de Kick, su título, canal y duración (o que ya no existe: Kick los
 * borra a los pocos días); de un canal de Kick, sus VODs disponibles; de un canal de
 * YouTube, sus videos (`tab`: videos | streams).
 */
export async function GET(req: NextRequest) {
  try {
    const url = (req.nextUrl.searchParams.get("url") ?? "").trim().slice(0, 300);
    if (!parseSource(url)) return jsonError("Pega el enlace de un video de YouTube o de un VOD de Kick.");
    const tab = req.nextUrl.searchParams.get("tab") === "streams" ? "streams" : "videos";
    return Response.json(await mediaFetch<SourceInfo>(`/source-info?${new URLSearchParams({ url, tab })}`, {
      signal: AbortSignal.timeout(60_000),
    }));
  } catch (err) {
    return handleError(err);
  }
}
