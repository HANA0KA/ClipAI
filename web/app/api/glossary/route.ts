import type { NextRequest } from "next/server";
import { cleanRules } from "@/lib/glossary";
import { applyRulesToAllClips } from "@/lib/glossary-apply";
import { readGlossary, updateGlossary } from "@/lib/glossary-store";
import { handleError, jsonError } from "@/lib/http";
import { safeId } from "@/lib/paths";

export const dynamic = "force-dynamic";

/** Glosario de correcciones (data/glossary.json). */
export async function GET() {
  try {
    return Response.json({ rules: await readGlossary() });
  } catch (err) {
    return handleError(err);
  }
}

/**
 * Añade (o cambia) una regla y la aplica a los subtítulos de todos los clips
 * existentes, salvo ``exceptClipId`` (el del estudio abierto, que la aplica en
 * su borrador). Los clips nuevos la reciben al crearse.
 */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as { from?: unknown; to?: unknown; exceptClipId?: unknown };
    const [rule] = cleanRules([{ from: body.from, to: body.to }]);
    if (!rule) return jsonError("Escribe la palabra mal transcrita y cómo debe decir (distintas entre sí, hasta 60 caracteres).");
    const rules = await updateGlossary((cur) => [...cur, rule]);
    const applied = await applyRulesToAllClips([rule], typeof body.exceptClipId === "string" ? safeId(body.exceptClipId) : undefined);
    return Response.json({ rules, rule, applied });
  } catch (err) {
    return handleError(err);
  }
}

/** Quita una regla (no deshace lo ya corregido en los clips). */
export async function DELETE(req: NextRequest) {
  try {
    const from = (req.nextUrl.searchParams.get("from") ?? "").trim().toLowerCase();
    if (!from) return jsonError("Falta la regla a quitar.");
    return Response.json({ rules: await updateGlossary((cur) => cur.filter((r) => r.from.toLowerCase() !== from)) });
  } catch (err) {
    return handleError(err);
  }
}
