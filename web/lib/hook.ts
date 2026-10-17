// Limpieza del gancho: misma regla que media/services/moments.py
// (`sanitize_hook`). El render la aplica siempre; aquí sirve para mostrar lo
// que se va a quemar y para guardar el texto ya limpio. El gancho es a la vez
// el título, la descripción, el texto de la portada y el nombre de los
// archivos: una frase corta con UN emoji al final («¡Le trajo un conejo vivo
// de regalo! 🐰»). El video la quema sin el emoji (`hookPlain`).

export const HOOK_MAX_WORDS = 10;
export const HOOK_MAX_CHARS = 64;
const QUOTES = /["`“”‘«»„‚‹›]|(?<![\p{L}\p{N}])['’]|['’](?![\p{L}\p{N}])/gu; // conserva «don't»
const TRIM = ".,;:-–—·/| ";

function trimChars(text: string, chars: string): string {
  let a = 0;
  let b = text.length;
  while (a < b && chars.includes(text[a])) a++;
  while (b > a && chars.includes(text[b - 1])) b--;
  return text.slice(a, b);
}

/** Un emoji (con su tono, variante o secuencia ZWJ): igual que `EMOJI_RE` de media/services/emoji_text.py. */
const EMOJI = /(?:\p{Extended_Pictographic}|\p{Regional_Indicator}{2})[\u{FE0F}\u{1F3FB}-\u{1F3FF}]*(?:\u200D\p{Extended_Pictographic}[\u{FE0F}\u{1F3FB}-\u{1F3FF}]*)*/gu;

export const stripEmoji = (t: string) => t.replace(EMOJI, " ").replace(/\s+/g, " ").trim();
export const hasEmoji = (t: string) => new RegExp(EMOJI.source, "u").test(t);
export const firstEmoji = (t: string): string | null => t.match(EMOJI)?.[0] ?? null;

/** El gancho como se quema en el video: limpio y sin emoji. */
export const hookPlain = (raw: string | null | undefined) => stripEmoji(sanitizeHook(raw));

export function sanitizeHook(raw: string | null | undefined): string {
  const emoji = firstEmoji(String(raw ?? ""));
  const text = sanitizePlain(stripEmoji(String(raw ?? "")), emoji ? emoji.length + 1 : 0);
  return text && emoji ? `${text} ${emoji}` : text;
}

function sanitizePlain(raw: string, reserve: number): string {
  let text = raw;
  text = text.replace(/#[\p{L}\p{N}_-]+/gu, " ");
  text = text.replace(/[*_\n]/g, " ").replace(QUOTES, " ");
  text = trimChars(text.replace(/\s+/g, " ").trim(), TRIM);
  if (!text) return "";
  const words = text.split(" ");
  if (words.length > HOOK_MAX_WORDS) text = words.slice(0, HOOK_MAX_WORDS).join(" ");
  const limit = HOOK_MAX_CHARS - reserve;
  if (text.length > limit) {
    const clipped = text.slice(0, limit + 1);
    const cut = clipped.lastIndexOf(" ");
    text = cut >= 20 ? clipped.slice(0, cut) : text.slice(0, limit);
  }
  text = trimChars(text.trim(), TRIM).trim();
  if (text.includes("¿") && !text.includes("?")) text = text.replaceAll("¿", "").trim();
  if (text.includes("¡") && !text.includes("!")) text = text.replaceAll("¡", "").trim();
  return text;
}

/** Emojis a mano para terminar el gancho (la IA ya propone uno del tema). */
export const HOOK_EMOJIS = ["🔥", "😱", "👀", "🤯", "💰", "😂", "❤️", "🤔", "⚡", "😳"];

/** El gancho sin sus emojis y con ``emoji`` al final (respeta el largo máximo). */
export function withEmoji(hook: string, emoji: string): string {
  const text = sanitizeHook(stripEmoji(hook));
  return text ? sanitizeHook(`${text} ${emoji}`) : hook;
}

export const HOOK_TYPE_LABEL: Record<string, string> = {
  question: "Pregunta",
  statement: "Afirmación",
  statistic: "Estadística",
  story: "Historia",
  contrast: "Contraste",
};

/** Segundos del gancho en pantalla en automático: misma regla que
 * media/services/ass_builder.py `hook_display_seconds` (duración de la
 * plantilla, tiempo de lectura y gancho hablado; tope de 6 s). */
/** Segundos del clip editado hasta que termina el gancho hablado, contando
 * los tramos que van antes (el avance). Mismo cálculo que `_spoken_hook` en
 * media/tasks/render.py; null si el tramo principal ya no está. */
export function spokenHookSeconds(arcSeconds: number | null | undefined, clipStart: number,
  segments: { start: number; end: number }[]): number | null {
  if (!arcSeconds) return null;
  const i = segments.findIndex((s) => Math.abs(s.start - clipStart) < 0.5);
  if (i < 0) return null;
  return arcSeconds + segments.slice(0, i).reduce((acc, s) => acc + (s.end - s.start), 0);
}

export function hookDisplaySeconds(text: string, templateSeconds: number | null | undefined,
  spoken: number | null | undefined): number {
  const n = hookPlain(text).split(" ").filter(Boolean).length;
  const reading = n ? 0.8 + 0.32 * n : 0;
  return Math.round(Math.min(6, Math.max(templateSeconds ?? 3, reading, spoken ?? 0)) * 100) / 100;
}

