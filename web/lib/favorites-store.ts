import "server-only";
import fs from "node:fs/promises";
import path from "node:path";
import { DATA_DIR } from "@/lib/paths";
import { cleanFavorites, DEFAULT_FAVORITES, type Favorites } from "@/lib/favorites";

const FILE = path.join(DATA_DIR, "favorites.json");

// Un cambio a la vez dentro del proceso (leer → modificar → escribir).
let queue: Promise<unknown> = Promise.resolve();

export async function readFavorites(): Promise<Favorites> {
  let raw: string;
  try {
    raw = await fs.readFile(FILE, "utf8");
  } catch {
    return structuredClone(DEFAULT_FAVORITES); // todavía no se guardó nada: los de fábrica
  }
  try {
    const j = JSON.parse(raw) as Partial<Record<keyof Favorites, unknown>>;
    return { kick: cleanFavorites("kick", j.kick), youtube: cleanFavorites("youtube", j.youtube) };
  } catch {
    return { kick: [], youtube: [] }; // archivo dañado: no se reponen los de fábrica sobre lo que hubiera
  }
}

/** Cambia los favoritos de forma atómica (tmp + rename); devuelve la lista resultante. */
export function updateFavorites(fn: (cur: Favorites) => Favorites): Promise<Favorites> {
  const run = queue.catch(() => undefined).then(async () => {
    const cur = await readFavorites();
    const next = fn(cur);
    const clean: Favorites = { kick: cleanFavorites("kick", next.kick), youtube: cleanFavorites("youtube", next.youtube) };
    await fs.mkdir(path.dirname(FILE), { recursive: true });
    const tmp = `${FILE}.${process.pid}.${Date.now()}.tmp`;
    await fs.writeFile(tmp, JSON.stringify({ version: 1, ...clean }, null, 1), { mode: 0o600 });
    await fs.rename(tmp, FILE);
    return clean;
  });
  queue = run;
  return run;
}
