import type { NextRequest } from "next/server";
import { mediaFetch } from "@/lib/media";

/** Vuelta de TikTok: FastAPI canjea el código y guarda el token cifrado. */
export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get("code");
  const state = req.nextUrl.searchParams.get("state");
  const home = new URL("/", req.nextUrl.origin);
  if (!code || !state) {
    home.searchParams.set("tiktok", req.nextUrl.searchParams.get("error_description") ?? "cancelado");
    return Response.redirect(home, 302);
  }
  try {
    await mediaFetch("/tiktok/token", { method: "POST", json: { code, state } });
    home.searchParams.set("tiktok", "conectado");
  } catch (err) {
    home.searchParams.set("tiktok", err instanceof Error ? err.message : "error");
  }
  return Response.redirect(home, 302);
}
