import type { NextRequest } from "next/server";
import { handleError } from "@/lib/http";
import { readNetworkTags, writeNetworkTags } from "@/lib/network-tags-store";

export const dynamic = "force-dynamic";

/** Hashtags fijos de YouTube e Instagram para todos los videos (data/network-hashtags.json). */
export async function GET() {
  try {
    return Response.json(await readNetworkTags());
  } catch (err) {
    return handleError(err);
  }
}

/** Reemplaza las fijas de una o las dos redes ({youtube?: texto|lista, instagram?: texto|lista}). */
export async function PUT(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as { youtube?: unknown; instagram?: unknown };
    return Response.json(await writeNetworkTags({ youtube: body.youtube, instagram: body.instagram }));
  } catch (err) {
    return handleError(err);
  }
}
