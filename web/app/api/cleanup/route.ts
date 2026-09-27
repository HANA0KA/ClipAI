import { handleError } from "@/lib/http";
import { mediaFetch } from "@/lib/media";

/** «Limpiar»: borra source.mp4 y audio.wav de todos los proyectos terminados. */
export async function POST() {
  try {
    return Response.json(await mediaFetch("/cleanup", { method: "POST" }));
  } catch (err) {
    return handleError(err);
  }
}
