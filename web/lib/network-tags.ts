// Hashtags fijos por red (YouTube e Instagram) para TODOS los videos: data/network-hashtags.json.
// Los comparten el servidor (network-tags-store.ts) y el navegador. La composición final por clip
// debe coincidir con `compose_network` de media/services/hashtags.py.

export type TagNetwork = "youtube" | "instagram";
export type NetworkTags = Record<TagNetwork, string[]>;

export const EMPTY_NETWORK_TAGS: NetworkTags = { youtube: [], instagram: [] };
/** Tope de etiquetas por red, sin contar #Shorts (YouTube ignora todas si hay más de 15; Instagram admite 5). */
export const NETWORK_TAG_CAP: Record<TagNetwork, number> = { youtube: 15, instagram: 5 };

const fold = (s: string) => s.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "");

/** «# Inteligencia artificial» → «#InteligenciaArtificial»; null si no sirve (misma regla que hashtags.normalize_tag). */
export function normalizeTag(raw: string): string | null {
  const parts = raw.trim().replace(/^#+/, "").split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (!parts.length) return null;
  const tag = parts.length === 1 ? parts[0] : parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
  if (tag.length > 30 || /^\d+$/.test(tag)) return null;
  return `#${tag}`;
}

/** Texto libre («#a, #b #c») o lista → etiquetas normalizadas sin repetidas (sin distinguir mayúsculas ni tildes). */
export function cleanTags(input: unknown, max = 30): string[] {
  const words = Array.isArray(input) ? input.map(String) : typeof input === "string" ? input.split(/[,\s]+/) : [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const w of words) {
    const t = w ? normalizeTag(w) : null;
    if (!t || seen.has(fold(t))) continue;
    seen.add(fold(t));
    out.push(t);
    if (out.length >= max) break;
  }
  return out;
}

/** Las fijas de la red primero, luego las del clip; sin repetidas y hasta el tope (#Shorts va delante en YouTube). */
export function composeNetwork(network: TagNetwork, clipSet: string[] | undefined, pinned: string[]): string[] {
  const seen = new Set<string>(network === "youtube" ? ["shorts"] : []);
  const out: string[] = [];
  for (const raw of [...pinned, ...(clipSet ?? [])]) {
    const t = normalizeTag(raw);
    if (!t || seen.has(fold(t))) continue;
    seen.add(fold(t));
    out.push(t);
  }
  const body = out.slice(0, NETWORK_TAG_CAP[network]);
  return network === "youtube" ? ["#Shorts", ...body] : body;
}
