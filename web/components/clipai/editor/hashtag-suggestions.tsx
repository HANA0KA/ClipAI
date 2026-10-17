"use client";

import { Check, Copy, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/client";
import type { HashtagSets, Health, Platform } from "@/lib/types";
import { useCopy } from "../copy-field";

const PLATFORMS: { id: Platform; label: string; hint: string }[] = [
  { id: "tiktok", label: "TikTok", hint: "3 a 5: uno amplio de la comunidad y el resto de nicho" },
  { id: "instagram", label: "Instagram", hint: "3 a 5 de nicho (Instagram admite como máximo 5)" },
  { id: "youtube", label: "YouTube Shorts", hint: "#Shorts y 2 o 3 del tema (YouTube muestra los 3 primeros)" },
];

/**
 * Hashtags sugeridos por red para el contenido de este clip. Copiar lleva el
 * juego al portapapeles; «Usar en el kit» lo pone en el campo de hashtags del
 * kit (lo que se envía al publicar); «Volver a sugerir» los rehace con los
 * tramos y las palabras actuales.
 */
export function HashtagSuggestions({ clipId, sets, health, onUse }: {
  clipId: string;
  sets: HashtagSets | null;
  health?: Health;
  onUse: (hashtags: string) => void;
}) {
  const base = health?.hashtagsBase ?? [];
  const [current, setCurrent] = useState<HashtagSets | null>(sets);
  const [busy, setBusy] = useState(false);
  const { copied, copy } = useCopy();

  async function regenerate() {
    setBusy(true);
    try {
      const fresh = await api<HashtagSets & { source: string }>(`/api/clips/${clipId}/hashtags`, { method: "POST" });
      setCurrent({ tiktok: fresh.tiktok, instagram: fresh.instagram, youtube: fresh.youtube });
      toast.success(fresh.source === "llm" ? "Hashtags sugeridos con IA" : "Hashtags sugeridos sin IA (palabras clave del clip)");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Hashtags por red</h3>
        <Button variant="ghost" size="sm" onClick={regenerate} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} {current ? "Volver a sugerir" : "Sugerir"}
        </Button>
      </div>
      {!current ? (
        <p className="text-xs text-muted-foreground">
          Este clip es de antes de las sugerencias por red. Pulsa «Sugerir» para crearlas con su contenido.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {PLATFORMS.map((p) => {
            const tags = current[p.id] ?? [];
            const text = tags.join(" ");
            return (
              <li key={p.id} className="rounded-lg border border-border p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium" title={p.hint}>{p.label}</span>
                  <span className="flex gap-1">
                    <Button variant="ghost" size="xs" disabled={!tags.length} onClick={() => copy(p.id, text)}>
                      {copied === p.id ? <Check className="text-success" /> : <Copy />} Copiar
                    </Button>
                    <Button variant="ghost" size="xs" disabled={!tags.length} onClick={() => {
                      onUse(text);
                      toast.success(`Hashtags de ${p.label} en el kit`);
                    }}>
                      Usar en el kit
                    </Button>
                  </span>
                </div>
                <p className="mt-1.5 flex flex-wrap gap-1">
                  {tags.length ? tags.map((t) => (
                    <span key={t} className="rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground">{t}</span>
                  )) : <span className="text-xs text-muted-foreground">Sin sugerencias</span>}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        Sobre el contenido de este clip, sin etiquetas de relleno
        {health?.hashtagsCreator ? ", con el creador del video original delante" : ""}
        {base.length ? <>, y las fijas de tu canal al final ({base.join(" ")}; se cambian con HASHTAGS_BASE en .env)</> : null}.
        Pega el juego de cada red al publicar allí; «Volver a sugerir» las aplica a los clips anteriores.
      </p>
    </div>
  );
}
