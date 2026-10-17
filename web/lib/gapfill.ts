// Huecos en el texto del clip: el pulido con Whisper a veces se salta un trozo
// de habla que la transcripción de YouTube sí trae. Misma lógica que
// media/services/gapfill.py (deben coincidir): un hueco es un tramo de
// ≥ MIN_GAP s dentro del clip sin ninguna palabra pulida y con al menos
// MIN_WORDS de la transcripción; se toman las palabras a más de MARGIN s de sus
// bordes (los tiempos de YouTube son menos exactos que los de Whisper).

export interface TimedWord {
  w: string;
  start: number;
  end: number;
}

export const MIN_GAP = 2.5;
export const MARGIN = 0.35;
export const MIN_WORDS = 2;
const NOISE = /^[[(♪].*[\])♪]$|^♪+$/; // «[Música]», «(aplausos)», «♪»

const mid = (w: TimedWord) => (w.start + w.end) / 2;
const key = (t: number) => Math.round(t * 1000);

/** Palabras de ``source`` que faltan en ``words`` dentro de ``ranges`` ([inicio, fin) del video fuente), en orden. */
export function gapCandidates(words: TimedWord[], source: TimedWord[], ranges: [number, number][]): TimedWord[] {
  const have = new Set(words.map((w) => key(w.start)));
  const out = new Map<number, TimedWord>();
  for (const [a, b] of ranges) {
    const inside = words.filter((w) => mid(w) >= a && mid(w) < b && w.w.trim()).sort((x, y) => x.start - y.start);
    // El margen solo va contra palabras vecinas, no contra los bordes del clip (ahí no hay nada que duplicar).
    const edges: [number, number, boolean][] = [...inside.map((w) => [w.start, w.end, true] as [number, number, boolean]), [b, b, false]];
    let reach = a;
    let prevWord = false;
    for (const [start, end, isWord] of edges) {
      if (start - reach >= MIN_GAP) {
        const lo = reach + (prevWord ? MARGIN : 0);
        const hi = start - (isWord ? MARGIN : 0);
        const got = source.filter((x) => mid(x) >= lo && mid(x) <= hi && x.w.trim() && !NOISE.test(x.w.trim()) && !have.has(key(x.start)));
        if (got.length >= MIN_WORDS) got.forEach((x) => out.set(key(x.start), x));
      }
      if (end >= reach) {
        reach = end;
        prevWord = isWord;
      }
    }
  }
  return [...out.entries()].sort((x, y) => x[0] - y[0]).map(([, w]) => w);
}
