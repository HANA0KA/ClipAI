// Glosario de correcciones (palabras que siempre se transcriben mal).
// Misma lógica que media/services/glossary.py: deben coincidir. Sin
// dependencias de servidor: lo usan el estudio (borrador) y las rutas de la API.

export interface GlossaryRule {
  from: string;
  to: string;
}

export const MAX_RULES = 500;
export const MAX_TEXT = 60;

const SPLIT = /^([^\p{L}\p{N}]*)([\s\S]*?)([^\p{L}\p{N}]*)$/u;
const norm = (t: unknown) => String(t ?? "").replace(/\s+/g, " ").trim();

/** [signos delante, palabra, signos detrás]. */
function parts(word: string): [string, string, string] {
  const m = SPLIT.exec(word);
  return m ? [m[1], m[2], m[3]] : ["", word, ""];
}

/** Reglas válidas: 1 a 60 caracteres, distintas de su reemplazo y una por «from» (la última manda). */
export function cleanRules(raw: unknown): GlossaryRule[] {
  const seen = new Map<string, GlossaryRule>();
  for (const r of Array.isArray(raw) ? raw : []) {
    if (!r || typeof r !== "object") continue;
    const from = norm((r as GlossaryRule).from).slice(0, MAX_TEXT);
    const to = norm((r as GlossaryRule).to).slice(0, MAX_TEXT);
    if (from && to && from !== to) {
      seen.delete(from.toLowerCase());
      seen.set(from.toLowerCase(), { from, to });
    }
  }
  return [...seen.values()].slice(0, MAX_RULES);
}

function compile(rules: GlossaryRule[]): { src: string[]; dst: string[] }[] {
  const out: { src: string[]; dst: string[] }[] = [];
  for (const r of cleanRules(rules)) {
    const src = r.from.split(" ").map((t) => parts(t)[1].toLowerCase());
    if (src.every(Boolean)) out.push({ src, dst: r.to.split(" ") });
  }
  return out.sort((a, b) => b.src.length - a.src.length); // primero las frases más largas
}

/**
 * Aplica las reglas a las palabras (en orden). Devuelve el texto nuevo de cada
 * una y los índices que cambiaron. Con otro número de palabras que la regla,
 * la primera lleva todo el texto y las demás quedan vacías (conservan su tiempo).
 * ``skip(i)``: palabras que no se tocan (p. ej. sin identidad única en el borrador).
 */
export function applyGlossary(
  words: { w: string }[], rules: GlossaryRule[], skip?: (i: number) => boolean,
): { texts: string[]; changed: number[]; hits: number } {
  const texts = words.map((w) => w.w);
  const changed = new Set<number>();
  const compiled = compile(rules);
  const cores = texts.map((t) => parts(t)[1].toLowerCase());
  let hits = 0;
  for (let i = 0; i < texts.length; i++) {
    for (const { src, dst } of compiled) {
      const n = src.length;
      if (i + n > texts.length || src.some((s, k) => cores[i + k] !== s || skip?.(i + k))) continue;
      const same = dst.length === n;
      const next = same ? dst : [dst.join(" "), ...Array<string>(n - 1).fill("")];
      const end = same ? n - 1 : 0;
      const lead = parts(texts[i])[0];
      const suffix = parts(texts[i + n - 1])[2];
      let did = false;
      for (let k = 0; k < n; k++) {
        const head = k === 0 ? lead : parts(texts[i + k])[0];
        const tail = k === end ? suffix : parts(texts[i + k])[2];
        const text = next[k] ? head + next[k] + tail : "";
        if (text !== texts[i + k]) {
          texts[i + k] = text;
          changed.add(i + k);
          did = true;
        }
      }
      if (did) hits++;
      i += n - 1;
      break;
    }
  }
  return { texts, changed: [...changed].sort((a, b) => a - b), hits };
}

/** Texto sin signos pegados a los extremos («Ibai,» → «Ibai»). */
export const coreText = (t: string) => parts(norm(t))[1];

/** Regla que resulta de corregir una palabra (null si no hay nada que recordar). */
export function ruleFromFix(before: string, after: string): GlossaryRule | null {
  const [rule] = cleanRules([{ from: coreText(before), to: coreText(after) }]);
  return rule ?? null;
}
