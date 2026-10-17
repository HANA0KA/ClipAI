// Streamers y canales favoritos del inicio (data/favorites.json). Lo comparten el servidor
// (favorites-store.ts) y el navegador: la validación es la misma en los dos lados.
import { youtubeChannelKey } from "@/lib/sources";

export type FavPlatform = "kick" | "youtube";
export interface Favorite {
  /** Kick: el usuario en minúsculas («westcol»). YouTube: «@handle», «channel/UC…», «c/nombre» o «user/nombre». */
  key: string;
  /** Nombre que se ve en el botón. */
  label: string;
}
export type Favorites = Record<FavPlatform, Favorite[]>;

export const MAX_FAVORITES = 20;
/** Lo que trae una instalación nueva (el ejemplo de Kick); quitarlo lo borra de verdad. */
export const DEFAULT_FAVORITES: Favorites = { kick: [{ key: "westcol", label: "Westcol" }], youtube: [] };

const KICK_SLUG = /^[A-Za-z0-9_-]{2,40}$/;

export function favoriteKey(platform: FavPlatform, raw: unknown): string | null {
  const text = typeof raw === "string" ? raw.trim().replace(/^@(?=[^@]*$)/, platform === "kick" ? "" : "@") : "";
  if (!text) return null;
  if (platform === "kick") return KICK_SLUG.test(text) ? text.toLowerCase() : null;
  return youtubeChannelKey(text, true);
}

export function cleanFavorite(platform: FavPlatform, raw: unknown): Favorite | null {
  if (!raw || typeof raw !== "object") return null;
  const { key, label } = raw as { key?: unknown; label?: unknown };
  const k = favoriteKey(platform, key);
  if (!k) return null;
  const name = typeof label === "string" ? label.replace(/\s+/g, " ").trim().slice(0, 40) : "";
  return { key: k, label: name || k.replace(/^(@|channel\/|c\/|user\/)/, "") };
}

/** Sin repetidos (los handles no distinguen mayúsculas), en orden y hasta MAX_FAVORITES. */
export function cleanFavorites(platform: FavPlatform, list: unknown): Favorite[] {
  const seen = new Set<string>();
  const out: Favorite[] = [];
  for (const item of Array.isArray(list) ? list : []) {
    const f = cleanFavorite(platform, item);
    if (!f || seen.has(f.key.toLowerCase())) continue;
    seen.add(f.key.toLowerCase());
    out.push(f);
    if (out.length >= MAX_FAVORITES) break;
  }
  return out;
}

export function isFavorite(list: Favorite[] | undefined, key: string): boolean {
  return !!list?.some((f) => f.key.toLowerCase() === key.toLowerCase());
}
