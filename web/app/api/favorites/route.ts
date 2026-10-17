import type { NextRequest } from "next/server";
import { cleanFavorite, favoriteKey, type FavPlatform, MAX_FAVORITES } from "@/lib/favorites";
import { readFavorites, updateFavorites } from "@/lib/favorites-store";
import { handleError, jsonError } from "@/lib/http";

export const dynamic = "force-dynamic";

const platformOf = (v: unknown): FavPlatform | null => (v === "kick" || v === "youtube" ? v : null);

/** Streamers de Kick y canales de YouTube favoritos (data/favorites.json). */
export async function GET() {
  try {
    return Response.json(await readFavorites());
  } catch (err) {
    return handleError(err);
  }
}

/** Guarda un favorito (o cambia su nombre si ya estaba). Devuelve las listas resultantes. */
export async function POST(req: NextRequest) {
  try {
    const body = (await req.json().catch(() => ({}))) as { platform?: unknown; key?: unknown; label?: unknown };
    const platform = platformOf(body.platform);
    const fav = platform ? cleanFavorite(platform, { key: body.key, label: body.label }) : null;
    if (!platform || !fav) return jsonError("Ese usuario o canal no es válido.");
    const cur = await readFavorites();
    const exists = cur[platform].some((f) => f.key.toLowerCase() === fav.key.toLowerCase());
    if (!exists && cur[platform].length >= MAX_FAVORITES) return jsonError(`Ya tienes ${MAX_FAVORITES} favoritos: quita alguno para guardar otro.`);
    return Response.json(await updateFavorites((all) => ({
      ...all,
      [platform]: exists ? all[platform].map((f) => (f.key.toLowerCase() === fav.key.toLowerCase() ? fav : f)) : [...all[platform], fav],
    })));
  } catch (err) {
    return handleError(err);
  }
}

/** Quita un favorito. */
export async function DELETE(req: NextRequest) {
  try {
    const platform = platformOf(req.nextUrl.searchParams.get("platform"));
    const key = platform ? favoriteKey(platform, req.nextUrl.searchParams.get("key")) : null;
    if (!platform || !key) return jsonError("Falta el favorito a quitar.");
    return Response.json(await updateFavorites((all) => ({
      ...all,
      [platform]: all[platform].filter((f) => f.key.toLowerCase() !== key.toLowerCase()),
    })));
  } catch (err) {
    return handleError(err);
  }
}
