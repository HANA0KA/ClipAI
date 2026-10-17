import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import { safeId } from "@/lib/paths";
import type { CoverSettings } from "@/lib/types";

export const dynamic = "force-dynamic";

type CoverPatch = Partial<CoverSettings> & { reset?: boolean };

const KEYS = ["text", "time", "position", "style", "dim", "reset"] as const;

/** Mensaje si algún ajuste no es válido (mismos límites que media `CoverIn`). */
function checkPatch(b: CoverPatch): string | null {
  if (typeof b !== "object" || b === null) return "Cuerpo no válido";
  if ("text" in b && b.text !== null && (typeof b.text !== "string" || b.text.length > 200)) return "Texto no válido (máx. 200 caracteres)";
  if ("time" in b && b.time !== null && !(typeof b.time === "number" && Number.isFinite(b.time) && b.time >= 0)) return "Segundo no válido";
  if ("position" in b && !["top", "center", "bottom"].includes(b.position as string)) return "Posición no válida";
  if ("style" in b && !["outline", "box"].includes(b.style as string)) return "Estilo no válido";
  if ("dim" in b && typeof b.dim !== "boolean") return "Valor no válido para oscurecer";
  return null;
}

/** Guarda los ajustes de la portada y la vuelve a generar. */
export async function POST(req: NextRequest, ctx: RouteContext<"/api/clips/[id]/cover">) {
  try {
    const id = safeId((await ctx.params).id);
    if (!(await prisma.clip.findUnique({ where: { id }, select: { id: true } }))) return jsonError("Clip no encontrado", 404);
    const body = (await req.json().catch(() => ({}))) as CoverPatch;
    const invalid = checkPatch(body);
    if (invalid) return jsonError(invalid, 400);
    // Solo las claves conocidas: media distingue «no enviado» de «null» (volver a automático).
    const patch = Object.fromEntries(KEYS.filter((k) => k in body).map((k) => [k, body[k]]));
    const made = await mediaFetch<{ coverPath: string; cover: CoverSettings; time: number; auto: boolean }>(
      `/clips/${id}/cover`,
      { method: "POST", json: patch, signal: AbortSignal.timeout(120_000) },
    );
    return Response.json(made);
  } catch (err) {
    return handleError(err);
  }
}
