import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { DATA_DIR } from "@/lib/paths";
import { cleanRules, type GlossaryRule } from "@/lib/glossary";

const FILE = path.join(DATA_DIR, "glossary.json");

// Un cambio a la vez dentro del proceso (leer → modificar → escribir).
let queue: Promise<unknown> = Promise.resolve();

export async function readGlossary(): Promise<GlossaryRule[]> {
  try {
    return cleanRules((JSON.parse(await fs.readFile(FILE, "utf8")) as { rules?: unknown }).rules);
  } catch {
    return [];
  }
}

/** Cambia el glosario de forma atómica (tmp + rename); devuelve las reglas resultantes. */
export function updateGlossary(fn: (rules: GlossaryRule[]) => GlossaryRule[]): Promise<GlossaryRule[]> {
  const run = queue.catch(() => undefined).then(async () => {
    const next = cleanRules(fn(await readGlossary()));
    await fs.mkdir(path.dirname(FILE), { recursive: true });
    const tmp = `${FILE}.${process.pid}.${Date.now()}.tmp`;
    await fs.writeFile(tmp, JSON.stringify({ version: 1, rules: next }, null, 1), { mode: 0o600 });
    await fs.rename(tmp, FILE);
    return next;
  });
  queue = run;
  return run;
}
