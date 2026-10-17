import fs from "node:fs/promises";
import path from "node:path";
import { TEMPLATES_DIR } from "@/lib/templates";
import type { TemplateInfo } from "@/lib/types";

const KEYS = ["id", "name", "description", "font", "highlight", "primary", "emphasis", "uppercase", "animation",
  "box_color", "background", "entrance", "emoji"] as const;

/** Plantillas de subtítulos (media/templates/*.json). */
export async function GET() {
  const dir = TEMPLATES_DIR;
  const files = (await fs.readdir(dir)).filter((f) => f.endsWith(".json")).sort();
  const out: TemplateInfo[] = [];
  for (const f of files) {
    const t = JSON.parse(await fs.readFile(path.join(dir, f), "utf8"));
    out.push({
      ...(Object.fromEntries(KEYS.map((k) => [k, t[k] ?? null])) as unknown as TemplateInfo),
      hookDuration: typeof t.hook?.duration === "number" ? t.hook.duration : null,
    });
  }
  return Response.json(out);
}
