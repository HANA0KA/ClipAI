// Orden de publicación de los clips de un proyecto y nombre de sus archivos.
//
// Del más reciente al más antiguo por fecha de creación. Los clips de un
// mismo análisis se crean con milisegundos de diferencia (en orden de
// puntaje), así que cuentan como creados a la vez: dentro de ese lote van del
// mejor al peor. Un clip combinado o un nuevo análisis forman su propio lote.
//
// El número de orden va en el nombre del video y de su portada, para que
// queden juntos y en orden en cualquier carpeta:
//   «03 - ¡Le trajo un conejo vivo! 🐰.mp4» y «03 - ¡Le trajo un conejo vivo! 🐰 - portada.jpg».

export interface Orderable {
  id: string;
  createdAt: Date | string;
  rank: number;
  score: number;
}

/** Clips creados con menos de esto de diferencia son del mismo lote. */
const BATCH_MS = 2 * 60_000;

const time = (c: Orderable) => new Date(c.createdAt).getTime();
const byRank = (a: Orderable, b: Orderable) => a.rank - b.rank || b.score - a.score || a.id.localeCompare(b.id);

/** Clips en orden de publicación (el primero es el que se publica primero). */
export function publishOrder<T extends Orderable>(clips: T[]): T[] {
  const newest = [...clips].sort((a, b) => time(b) - time(a) || byRank(a, b));
  const out: T[] = [];
  let batch: T[] = [];
  let head = 0;
  for (const c of newest) {
    if (batch.length && head - time(c) > BATCH_MS) {
      out.push(...batch.sort(byRank));
      batch = [];
    }
    if (!batch.length) head = time(c);
    batch.push(c);
  }
  out.push(...batch.sort(byRank));
  return out;
}

/** id → posición (1, 2, …) en el orden de publicación. */
export function publishPositions(clips: Orderable[]): Map<string, number> {
  return new Map(publishOrder(clips).map((c, i) => [c.id, i + 1]));
}

/** El gancho como nombre de archivo: con su emoji y signos («¡Le trajo un
 * conejo vivo! 🐰»), sin hashtags ni lo que los sistemas de archivos no
 * aceptan (separadores de ruta y ``: * ? " < > |``). Misma regla que
 * `_download_base` de media/main.py. */
export function fileTitle(title: string, fallback = "clip"): string {
  const t = title
    .replace(/#[\p{L}\p{N}_]+/gu, " ")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "")
    .replace(/[\p{Cf}\ufe0e\ufe0f]/gu, "") // ZWJ de emojis compuestos (😵‍💫) y selectores: Chrome los rechaza («Name is not allowed»)
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[\s.-]+|[\s.-]+$/g, "");
  const chars = Array.from(t); // por caracteres, no por unidades UTF-16: un emoji no se parte
  const cut = chars.length > 70 ? chars.slice(0, 70).join("").replace(/\s+\S*$/, "") : t;
  return cut || fallback;
}

/** «03 - Título» (sin extensión): base común del video y de su portada. */
export function fileBase(position: number | null, title: string, total = 0): string {
  const name = fileTitle(title);
  if (position == null) return name;
  return `${String(position).padStart(Math.max(2, String(total).length), "0")} - ${name}`;
}
