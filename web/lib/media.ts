import "server-only";
import { MEDIA_API_URL } from "@/lib/paths";

export class MediaUnavailable extends Error {}

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
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? String(data.detail) : text;
    throw new Error(detail || `Error ${res.status} del servicio de procesamiento`);
  }
  return data as T;
}

export function enqueueJob(type: string, targetId: string, payload: Record<string, unknown> = {}) {
  return mediaFetch<{ id: string | null }>("/jobs", { method: "POST", json: { type, targetId, payload } });
}
