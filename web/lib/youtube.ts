// Id del video en un enlace de YouTube (misma regla que
// media/services/source_cache.py `youtube_id`). Solo se aceptan enlaces a UN
// video: yt-dlp recorre listas, canales y búsquedas entrada por entrada.

const ID_RE = /^[A-Za-z0-9_-]{11}$/;
const VIDEO_PATHS = new Set(["shorts", "live", "embed", "v"]);

export function youtubeVideoId(raw: string): string | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  let u: URL;
  try {
    u = new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase();
  let id: string | null = null;
  if (host === "youtu.be" || host.endsWith(".youtu.be")) {
    id = u.pathname.replace(/^\/+/, "").split("/")[0] || null;
  } else if (host === "youtube.com" || host.endsWith(".youtube.com")) {
    if (u.pathname === "/watch") id = u.searchParams.get("v");
    else {
      const parts = u.pathname.split("/").filter(Boolean);
      if (parts.length >= 2 && VIDEO_PATHS.has(parts[0])) id = parts[1];
    }
  }
  return id && ID_RE.test(id) ? id : null;
}
