"use client";

import { Crosshair, Download, ImageIcon, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/client";
import { saveFileAs } from "@/lib/export-folder";
import { timecode } from "@/lib/format";
import { HOOK_MAX_CHARS, sanitizeHook } from "@/lib/hook";
import type { ClipDTO, CoverPosition, CoverSettings, CoverStyle } from "@/lib/types";
import { Choice } from "./choice";

type Patch = Partial<CoverSettings> & { reset?: boolean };

const RATIO: Record<ClipDTO["aspect"], string> = { vertical: "9 / 16", square: "1 / 1", original: "16 / 9" };

/**
 * Portada del clip: un cuadro del video con el gancho en grande, lista para
 * subir como miniatura en TikTok, Reels o Shorts. Se crea sola al renderizar;
 * aquí se cambia el texto, la posición, el estilo y el cuadro, y se descarga.
 * Cada cambio la vuelve a generar en el servicio media (≈ medio segundo).
 * El padre lo monta con `key` = versión de la portada: si otra pestaña o un
 * render la cambia, se reinicia con lo del servidor (sin pisar lo que escribes
 * mientras tanto con un efecto).
 */
export function CoverPanel({ clip, hook, pickTime, toClipTime, onUpdated }: {
  clip: ClipDTO;
  /** Gancho actual del estudio (lo que muestra la portada si no hay texto propio). */
  hook: string;
  /** Segundo del video fuente bajo el cursor, o null si está fuera del clip. */
  pickTime: () => number | null;
  /** Segundo del video fuente → segundo del clip editado (null si ya no está). */
  toClipTime: (t: number) => number | null;
  onUpdated: () => void;
}) {
  const [cover, setCover] = useState<CoverSettings>(clip.cover);
  const [text, setText] = useState(clip.cover.text ?? "");
  const [url, setUrl] = useState<string | null>(clip.coverUrl);
  const [busy, setBusy] = useState(false);

  const picked = cover.time == null ? null : toClipTime(cover.time);
  const textDirty = (text.trim() || null) !== cover.text;
  const rendered = clip.renderStatus === "DONE" || !!clip.coverUrl;
  const shown = sanitizeHook(text) || sanitizeHook(hook);

  async function apply(patch: Patch) {
    setBusy(true);
    try {
      const made = await api<{ coverPath: string; cover: CoverSettings; time: number; auto: boolean }>(
        `/api/clips/${clip.id}/cover`, { method: "POST", json: patch },
      );
      setCover(made.cover);
      setText(made.cover.text ?? "");
      setUrl(`/media/files/${made.coverPath.split("/").map(encodeURIComponent).join("/")}?v=${Date.now()}`);
      onUpdated();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function commitText() {
    const next = text.trim() ? text.trim() : null;
    if (next !== cover.text) void apply({ text: next });
  }

  function useCurrentFrame() {
    const t = pickTime();
    if (t == null) return void toast.info("Pon el cursor del reproductor dentro del clip y vuelve a pulsar.");
    void apply({ time: Math.round(t * 1000) / 1000 });
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Portada</h3>
        {!url && rendered && (
          <Button size="sm" disabled={busy} onClick={() => void apply({})}>
            <ImageIcon /> Crear portada
          </Button>
        )}
        {url && (textDirty || busy ? (
          <Button size="sm" variant="secondary" disabled title="Aplica el texto primero">
            <Download /> Descargar portada
          </Button>
        ) : (
          <Button size="sm" variant="secondary" title="Eliges dónde guardarla y con qué nombre"
            onClick={() => saveFileAs(clip.coverDownloadUrl ?? url, `${clip.fileBase} - portada.jpg`, "image")
              .then((ok) => ok && toast.success("Portada guardada"))
              .catch((e: Error) => toast.error(`No se pudo guardar: ${e.message}`))}>
            <Download /> Descargar portada
          </Button>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-[150px_1fr]">
        <div className="relative w-[150px] overflow-hidden rounded-lg bg-well" style={{ aspectRatio: RATIO[clip.aspect] }}>
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element -- imagen local servida por media
            <img src={url} alt={`Portada: ${shown}`} className="size-full object-cover" />
          ) : (
            <div className="grid size-full place-items-center p-3 text-center text-xs text-muted-foreground">
              <span><ImageIcon className="mx-auto mb-1 size-5" />{rendered ? "Sin portada aún" : "Se crea al renderizar"}</span>
            </div>
          )}
          {busy && (
            <div className="absolute inset-0 grid place-items-center bg-black/40">
              <Loader2 className="size-5 animate-spin text-white" />
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-3">
          <div>
            <Label htmlFor="cover-text" className="text-xs text-muted-foreground">Texto (vacío = el gancho)</Label>
            <div className="mt-1 flex gap-2">
              <Input
                id="cover-text"
                value={text}
                maxLength={120}
                placeholder={sanitizeHook(hook) || "Gancho del clip"}
                disabled={!rendered || busy}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitText();
                  if (e.key === "Escape") setText(cover.text ?? "");
                }}
              />
              {textDirty && (
                <Button size="sm" disabled={!rendered || busy} onClick={commitText}>Aplicar</Button>
              )}
            </div>
            {text && sanitizeHook(text) !== text.trim() && (
              <p className="mt-1 text-xs text-muted-foreground">
                Se verá como «{sanitizeHook(text)}» (máx. 10 palabras / {HOOK_MAX_CHARS} caracteres).
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Choice<CoverPosition>
              label="Posición del texto"
              value={cover.position}
              disabled={!rendered || busy}
              onChange={(v) => void apply({ position: v })}
              options={[{ value: "top", label: "Arriba" }, { value: "center", label: "Centro" }, { value: "bottom", label: "Abajo" }]}
            />
            <Choice<CoverStyle>
              label="Estilo del texto"
              value={cover.style}
              disabled={!rendered || busy}
              onChange={(v) => void apply({ style: v })}
              options={[
                { value: "outline", label: "Contorno", hint: "Letra blanca con borde negro y acento de color" },
                { value: "box", label: "Caja", hint: "La caja del gancho de la plantilla" },
              ]}
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <Switch checked={cover.dim} disabled={!rendered || busy} onCheckedChange={(v) => void apply({ dim: v })} />
            Oscurecer detrás del texto
          </label>

          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">
              Cuadro:{" "}
              {cover.time == null
                ? "automático (rostro, nitidez y buena luz)"
                : picked == null
                  ? "el que elegiste ya no está en el clip; se usa el automático"
                  : `elegido a mano (${timecode(picked, true)} del clip)`}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" disabled={!rendered || busy} onClick={useCurrentFrame}>
                <Crosshair /> Usar el cuadro del reproductor
              </Button>
              <Button size="sm" variant="ghost" disabled={!rendered || busy || cover.time == null}
                onClick={() => void apply({ time: null })}>
                <Sparkles /> Automático
              </Button>
              <Button size="sm" variant="ghost" disabled={!rendered || busy} onClick={() => void apply({ reset: true })}>
                <RotateCcw /> Restablecer
              </Button>
            </div>
          </div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        1080×1920 con el texto dentro de la zona que TikTok e Instagram muestran en el perfil. Súbela como portada o
        miniatura al publicar.
      </p>
    </section>
  );
}
