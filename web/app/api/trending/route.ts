import type { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { handleError, jsonError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";
import type { TrendingResponse } from "@/lib/types";
import { parseSource } from "@/lib/sources";

export const dynamic = "force-dynamic";

const PERIODS = new Set(["day", "week", "month"]);
const SORTS = new Set(["views", "date", "relevance"]);
const DURATIONS = new Set(["long", "medium", "any"]);
const LANG = /^(auto|any|[a-z]{2,3})$/;

/**
 * Videos de YouTube con potencial para clips (media/services/trending.py):
 * ?q= (vacío = los temas de TRENDING_TOPICS) &period= &sort= &duration= &lang= &refresh=1.
 * Cada resultado trae ``project``: el proyecto de ClipAI que ya usa ese video, si hay.
 */
export async function GET(req: NextRequest) {
  try {
    const p = req.nextUrl.searchParams;
    const period = p.get("period") ?? "week";
    const sort = p.get("sort") ?? "views";
    const duration = p.get("duration") ?? "long";
    const lang = p.get("lang") ?? "auto";
    if (!PERIODS.has(period) || !SORTS.has(sort) || !DURATIONS.has(duration) || !LANG.test(lang)) return jsonError("Filtros no válidos");
    const qs = new URLSearchParams({ q: (p.get("q") ?? "").trim().slice(0, 100), period, sort, duration, lang });
    if (p.get("refresh") === "1") qs.set("refresh", "true");
    const data = await mediaFetch<Omit<TrendingResponse, "items"> & { items: Omit<TrendingResponse["items"][number], "project">[] }>(
      `/trending?${qs}`, { signal: AbortSignal.timeout(180_000) },
    );
    const used = new Map<string, string>();
    for (const proj of await prisma.project.findMany({ where: { sourceType: "youtube" }, select: { id: true, sourceUrl: true } })) {
      const src = proj.sourceUrl ? parseSource(proj.sourceUrl) : null;
      if (src?.type === "youtube" && src.kind === "video" && src.id) used.set(src.id, proj.id);
    }
    return Response.json({ ...data, items: data.items.map((i) => ({ ...i, project: used.get(i.id) ?? null })) });
  } catch (err) {
    return handleError(err);
  }
}
