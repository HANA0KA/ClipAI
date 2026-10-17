import "server-only";
import { MEDIA_API_URL } from "@/lib/paths";

export class MediaUnavailable extends Error {}

/** Respuesta de error del servicio Python, con su código (400, 404, 409…). */
export class MediaHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** Llamada al servicio Python (FastAPI) en 127.0.0.1. */
export async function mediaFetch<T = unknown>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`${MEDIA_API_URL}${path}`, {
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      cache: "no-store",
      signal: rest.signal ?? AbortSignal.timeout(20_000),
    });
  } catch {
    throw new MediaUnavailable(
      "El servicio de procesamiento (FastAPI) no responde en " + MEDIA_API_URL + ". Arranca la app con ./start.sh.",
    );
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.ok) throw new MediaHttpError("Respuesta no válida del servicio de procesamiento", 502);
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? detailText(data.detail) : text;
    throw new MediaHttpError(detail || `Error ${res.status} del servicio de procesamiento`, res.status);
  }
  return data as T;
}

/** `detail` de FastAPI → texto: un mensaje, o la lista de campos no válidos (422). */
function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const fields = detail
      .map((d) => (d && typeof d === "object" && "loc" in d && Array.isArray(d.loc) ? String(d.loc.at(-1)) : ""))
      .filter(Boolean);
    return `Datos no válidos${fields.length ? `: ${[...new Set(fields)].join(", ")}` : ""}`;
  }
  return detail == null ? "" : JSON.stringify(detail);
}

export function enqueueJob(type: string, targetId: string, payload: Record<string, unknown> = {}) {
  return mediaFetch<{ id: string | null }>("/jobs", { method: "POST", json: { type, targetId, payload } });
}
