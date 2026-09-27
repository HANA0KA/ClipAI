import { mediaFetch } from "@/lib/media";
import type { Health } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return Response.json(await mediaFetch<Health>("/health", { signal: AbortSignal.timeout(4000) }));
  } catch (err) {
    return Response.json({ ok: false, error: err instanceof Error ? err.message : String(err) } satisfies Health);
  }
}
