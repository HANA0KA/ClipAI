/**
 * Protección de la web local contra páginas ajenas (CSRF y DNS rebinding).
 * Mismas reglas que `media/services/local_guard.py`: deben coincidir.
 *
 * - `Host` debe ser un nombre local (127.0.0.1, localhost, ::1 o los de `ALLOWED_HOSTS`).
 * - Si llega `Origin`, debe ser exactamente el origen de esta misma web.
 * - `Sec-Fetch-Site: cross-site` solo se admite en lecturas (GET/HEAD).
 * - `/media/*` (reenvío al servicio de procesamiento) solo deja leer archivos y descargas:
 *   el resto de la API de FastAPI no se expone al navegador.
 */
const LOOPBACK = ["127.0.0.1", "localhost", "::1"];
const SAFE_METHODS = ["GET", "HEAD"];
const MEDIA_READ_PREFIXES = ["/media/files/", "/media/download/"];

function hostnameOf(host: string): string | null {
  try {
    return new URL(`http://${host.trim()}`).hostname.replace(/^\[|\]$/g, "").toLowerCase() || null;
  } catch {
    return null;
  }
}

function allowedHosts(): Set<string> {
  const extra = (process.env.ALLOWED_HOSTS ?? "").split(",").map((h) => h.trim().toLowerCase()).filter(Boolean);
  return new Set([...LOOPBACK, ...extra]);
}

/** Motivo del rechazo (403), o null si la petición puede seguir. */
export function rejectReason(req: { method: string; pathname: string; headers: Headers }): string | null {
  const hosts = allowedHosts();
  const hostHeader = req.headers.get("host") ?? "";
  const name = hostnameOf(hostHeader);
  if (!name || !hosts.has(name)) return "Host no permitido";

  const origin = req.headers.get("origin");
  if (origin !== null) {
    let o: URL;
    try {
      o = new URL(origin);
    } catch {
      return "Origin no permitido";
    }
    if (!["http:", "https:"].includes(o.protocol) || o.host.toLowerCase() !== hostHeader.trim().toLowerCase()) {
      return "Origin no permitido";
    }
  }

  const method = req.method.toUpperCase();
  const safe = SAFE_METHODS.includes(method);
  if (req.headers.get("sec-fetch-site") === "cross-site" && !safe) return "Petición entre sitios no permitida";

  if (req.pathname.startsWith("/media/") && !(safe && MEDIA_READ_PREFIXES.some((p) => req.pathname.startsWith(p)))) {
    return "Ruta no disponible";
  }
  return null;
}
