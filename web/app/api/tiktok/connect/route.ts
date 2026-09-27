import { handleError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";

/** Redirige a TikTok para autorizar tu cuenta una vez (scope video.upload). */
export async function GET() {
  try {
    const { url } = await mediaFetch<{ url: string }>("/tiktok/auth-url");
    return Response.redirect(url, 302);
  } catch (err) {
    return handleError(err);
  }
}
