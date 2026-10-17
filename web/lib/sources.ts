// Fuentes de video que ClipAI sabe descargar: YouTube y Kick (VODs). Misma
// regla que media/services/sources.py `parse` (deben coincidir).
import { youtubeVideoId } from "@/lib/youtube";

export type SourceType = "youtube" | "kick";
export type SourceKind = "video" | "channel" | "clip";
export interface ParsedSource {
  type: SourceType;
  kind: SourceKind;
  id: string | null;
  channel: string | null;
}

const KICK_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KICK_SLUG = /^[A-Za-z0-9_-]{2,40}$/;
const YT_HANDLE = /^@[A-Za-z0-9._-]{3,30}$/;
const YT_CHANNEL_ID = /^UC[A-Za-z0-9_-]{22}$/;
const YT_LEGACY_NAME = /^[A-Za-z0-9._-]{1,60}$/;
const KICK_RESERVED = new Set(["video", "videos", "categories", "category", "search", "browse", "following", "dashboard",
  "community-guidelines", "terms-of-service", "privacy-policy", "help", "api", "clips"]);

/**
 * Clave canónica de un canal de YouTube («@handle», «channel/UC…», «c/nombre», «user/nombre») o null.
 * Con `allowBare` también acepta el handle o el id sueltos (lo que se escribe en el panel de canales);
 * `parseSource` no: un texto sin sitio no es un enlace. Misma regla que `youtube_channel_key` de sources.py.
 */
export function youtubeChannelKey(raw: string | null | undefined, allowBare = false): string | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  if (allowBare && !text.includes("/")) {
    const bare = text.startsWith("@") ? text : YT_HANDLE.test(`@${text}`) && !YT_CHANNEL_ID.test(text) ? `@${text}` : text;
    if (YT_HANDLE.test(bare)) return bare;
    if (YT_CHANNEL_ID.test(bare)) return `channel/${bare}`;
  }
  let u: URL;
  try {
    u = new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase();
  if (!(host === "youtube.com" || host.endsWith(".youtube.com"))) return null;
  const parts = u.pathname.split("/").filter(Boolean).map((p) => {
    try {
      return decodeURIComponent(p);
    } catch {
      return p;
    }
  });
  if (!parts.length) return null;
  if (parts[0].startsWith("@")) return YT_HANDLE.test(parts[0]) ? parts[0] : null;
  if (parts.length >= 2 && parts[0] === "channel") return YT_CHANNEL_ID.test(parts[1]) ? `channel/${parts[1]}` : null;
  if (parts.length >= 2 && (parts[0] === "c" || parts[0] === "user")) return YT_LEGACY_NAME.test(parts[1]) ? `${parts[0]}/${parts[1]}` : null;
  return null;
}

export function parseSource(raw: string | null | undefined): ParsedSource | null {
  const text = (raw ?? "").trim();
  if (!text) return null;
  let u: URL;
  try {
    u = new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    return null;
  }
  const host = u.hostname.toLowerCase();
  if (host === "kick.com" || host.endsWith(".kick.com")) {
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts.length >= 3 && parts[1] === "videos" && KICK_UUID.test(parts[2])) {
      return { type: "kick", kind: "video", id: parts[2].toLowerCase(), channel: parts[0] };
    }
    if (parts.length === 2 && parts[0] === "video" && KICK_UUID.test(parts[1])) {
      return { type: "kick", kind: "video", id: parts[1].toLowerCase(), channel: null };
    }
    if (parts.length && !KICK_RESERVED.has(parts[0]) && KICK_SLUG.test(parts[0])) {
      if ((parts.length >= 3 && parts[1] === "clips") || u.searchParams.has("clip")) {
        return { type: "kick", kind: "clip", id: null, channel: parts[0] };
      }
      if (parts.length === 1 || parts[1] === "videos" || parts[1] === "clips") {
        return { type: "kick", kind: "channel", id: parts[0], channel: parts[0] };
      }
    }
    return null;
  }
  const vid = youtubeVideoId(text);
  if (vid) return { type: "youtube", kind: "video", id: vid, channel: null };
  const ch = youtubeChannelKey(text);
  return ch ? { type: "youtube", kind: "channel", id: ch, channel: ch } : null;
}

/** «1:30:00», «90:00», «5400» o «1h30m» → segundos; null si está vacío o no se entiende. */
export function parseClock(raw: string): number | null {
  const t = raw.trim().toLowerCase();
  if (!t) return null;
  const hms = /^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s?)?$/.exec(t);
  if (hms && /[hm]/.test(t)) return (Number(hms[1] ?? 0) * 3600) + (Number(hms[2] ?? 0) * 60) + Number(hms[3] ?? 0);
  if (!/^\d+(:\d{1,2}){0,2}$/.test(t)) return null;
  return t.split(":").reduce((acc, p) => acc * 60 + Number(p), 0);
}

export function formatClock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
