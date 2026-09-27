import { MediaUnavailable } from "@/lib/media";

export function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status });
}

/** Convierte excepciones de los handlers en respuestas JSON legibles. */
export function handleError(err: unknown) {
  if (err instanceof MediaUnavailable) return jsonError(err.message, 503);
  const message = err instanceof Error ? err.message : String(err);
  if (message === "id inválido") return jsonError("Identificador inválido", 400);
  console.error(err);
  return jsonError(message, 500);
}
