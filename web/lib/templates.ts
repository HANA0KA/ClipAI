import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { ROOT_DIR } from "@/lib/paths";

export const TEMPLATES_DIR = path.join(ROOT_DIR, "media", "templates");
const TEMPLATE_ID = /^[a-z0-9-]{2,40}$/;

/** Ids de las plantillas de subtítulos (media/templates/*.json). */
export async function templateIds(): Promise<string[]> {
  return (await fs.readdir(TEMPLATES_DIR)).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort();
}

/** Plantilla válida y existente, o null. */
export async function validTemplate(id: unknown): Promise<string | null> {
  if (typeof id !== "string" || !TEMPLATE_ID.test(id)) return null;
  return (await templateIds()).includes(id) ? id : null;
}
