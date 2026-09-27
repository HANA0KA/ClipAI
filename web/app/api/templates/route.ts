import fs from "node:fs/promises";
import path from "node:path";
import { ROOT_DIR } from "@/lib/paths";
import type { TemplateInfo } from "@/lib/types";

/** Plantillas de subtítulos (media/templates/*.json). */
export async function GET() {
  const dir = path.join(ROOT_DIR, "media", "templates");
  const files = (await fs.readdir(dir)).filter((f) => f.endsWith(".json")).sort();
  const out: TemplateInfo[] = [];
  for (const f of files) {
    const t = JSON.parse(await fs.readFile(path.join(dir, f), "utf8"));
    out.push({ id: t.id, name: t.name, description: t.description, font: t.font, highlight: t.highlight, primary: t.primary });
  }
  return Response.json(out);
}
