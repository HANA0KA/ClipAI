import type { NextRequest } from "next/server";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { mediaUrl } from "@/lib/serialize";
import type { FontInfo } from "@/lib/types";

export const dynamic = "force-dynamic";

type RawFont = Omit<FontInfo, "url">;
const withUrl = (f: RawFont): FontInfo => ({ ...f, url: mediaUrl(`fonts/${f.file}`) ?? "" });

/** Fuentes para subtítulos: las incluidas y las que subiste. */
export async function GET() {
  try {
    return Response.json((await mediaFetch<RawFont[]>("/fonts")).map(withUrl));
  } catch (err) {
    return handleError(err);
  }
}

/** Sube una fuente TTF/OTF (cuerpo crudo, ?name=archivo.ttf). */
export async function POST(req: NextRequest) {
  try {
    const name = req.nextUrl.searchParams.get("name") ?? "";
    if (!/\.(ttf|otf)$/i.test(name)) return jsonError("Sube una fuente .ttf u .otf.");
    const body = await req.arrayBuffer();
    if (body.byteLength > 15 * 1024 * 1024) return jsonError("La fuente pesa más de 15 MB.");
    const font = await mediaFetch<RawFont>(`/fonts?name=${encodeURIComponent(name)}`, {
      method: "POST",
      body,
      headers: { "Content-Type": "application/octet-stream" },
    });
    return Response.json(withUrl(font), { status: 201 });
  } catch (err) {
    return handleError(err);
  }
}
