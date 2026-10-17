"use client";

import { BookMarked, Highlighter, Loader2, Replace, TextCursorInput, X } from "lucide-react";
import { memo, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import type { Segment } from "@/lib/edit-doc";
import { type GlossaryRule, ruleFromFix } from "@/lib/glossary";
import type { CaptionWord } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type WordOverride, wordKey } from "./use-studio";

interface Props {
  words: CaptionWord[];
  overrides: Record<string, WordOverride>;
  original: Map<string, string>;
  segments: Segment[];
  source: string;
  onEdit: (key: string, patch: Partial<WordOverride>) => void;
  onSeek: (t: number) => void;
  /** Corrige todas las coincidencias en este clip (borrador); ``remember``: además guarda la regla para siempre. */
  onReplaceAll: (rule: GlossaryRule, remember: boolean) => Promise<void> | void;
  /** Palabras que Whisper se saltó y la transcripción de YouTube sí trae, dentro del clip. */
  missing: number;
  onFillMissing: () => Promise<void>;
}

/**
 * Palabras del clip. Clic: el visor va a esa palabra (o, en modo destacar,
 * la marca para que salga en el color de énfasis). Doble clic: corregirla.
 * Vaciar una palabra la quita del subtítulo sin perderla. Los tiempos no cambian.
 */
export const WordsPanel = memo(function WordsPanel({
  words, overrides, original, segments, source, onEdit, onSeek, onReplaceAll, missing, onFillMissing,
}: Props) {
  const [filling, setFilling] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [fix, setFix] = useState<GlossaryRule | null>(null); // última corrección: se ofrece aplicarla a las demás
  const [marking, setMarking] = useState(false);
  const inside = useMemo(
    () => (w: CaptionWord) => segments.some((s) => (w.start + w.end) / 2 >= s.start && (w.start + w.end) / 2 < s.end),
    [segments],
  );
  if (!words.length) return <p className="text-sm text-muted-foreground">No hay palabras para este tramo.</p>;
  const marked = words.filter((w) => overrides[wordKey(w.t)]?.hl).length;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {source === "whisper" ? "Pulidas con Whisper" : "De los subtítulos"}. Todo el texto del clip
          {words.length ? ` (${words.length} palabras)` : ""}: doble clic en una palabra para corregirla.
        </span>
        <Toggle
          size="sm"
          variant="pink"
          pressed={marking}
          onPressedChange={setMarking}
          aria-label="Modo destacar palabras"
        >
          <Highlighter /> Destacar{marked ? ` (${marked})` : ""}
        </Toggle>
      </div>
      {missing > 0 && (
        <div role="status" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm">
          <span>
            Al pulido con Whisper se le pasó habla del clip: la transcripción de YouTube trae{" "}
            <b className="font-semibold">{missing} palabra(s)</b> más en esos huecos.
          </span>
          <Button type="button" size="sm" className="ml-auto" disabled={filling}
            title="Añade el texto que falta (con el glosario aplicado). Después hay que renderizar de nuevo."
            onClick={async () => { setFilling(true); try { await onFillMissing(); } finally { setFilling(false); } }}>
            {filling ? <Loader2 className="animate-spin" /> : <TextCursorInput />} Completar el texto
          </Button>
        </div>
      )}
      {fix && (
        <div role="status" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3 py-2 text-sm">
          <span>
            ¿Corregir también todas las <b className="font-semibold">«{fix.from}»</b> por <b className="font-semibold">«{fix.to}»</b>?
          </span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            <Button type="button" size="sm" variant="secondary" onClick={() => { void onReplaceAll(fix, false); setFix(null); }}>
              <Replace /> En este clip
            </Button>
            <Button type="button" size="sm" onClick={() => { void onReplaceAll(fix, true); setFix(null); }}
              title="Guarda la regla en el glosario: se aplica a los demás clips y a los que crees después">
              <BookMarked /> Siempre
            </Button>
            <Button type="button" size="icon-sm" variant="ghost" aria-label="Descartar" onClick={() => setFix(null)}><X /></Button>
          </div>
        </div>
      )}
      <p className="pr-2 text-[15px] leading-8">
        {words.map((w, i) => {
          const k = wordKey(w.t);
          // Whisper a veces deja dos palabras con el mismo inicio («O sea»): la
          // identidad sigue siendo el inicio, pero la clave de React debe ser única.
          const key = `${k}-${i}`;
          const o = overrides[k] ?? { w: w.w, hl: w.hl };
          const edited = original.has(k) && original.get(k) !== o.w;
          if (editing === k) {
            return (
              <input
                key={key}
                autoFocus
                defaultValue={o.w}
                size={Math.max(2, o.w.length + 1)}
                aria-label="Corregir palabra"
                className="mx-0.5 rounded bg-muted px-1 text-foreground outline-none ring-2 ring-ring"
                onBlur={(e) => {
                  const next = e.target.value.replace(/\s+/g, " ").trim();
                  if (e.target.value.trim() !== o.w) {
                    onEdit(k, { w: next });
                    setFix(ruleFromFix(o.w, next));
                  }
                  setEditing(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                  if (e.key === "Escape") setEditing(null);
                }}
              />
            );
          }
          return (
            <button
              type="button"
              key={key}
              onClick={() => (marking ? onEdit(k, { hl: !o.hl }) : onSeek(w.start))}
              onDoubleClick={() => setEditing(k)}
              title={marking ? "Clic: destacar o quitar" : "Clic: ir a esta palabra. Doble clic: corregir"}
              className={cn(
                "mx-[1px] rounded px-0.5 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                !inside(w) && "text-muted-foreground/60",
                o.hl && "bg-primary/20 font-semibold text-primary",
                edited && "underline decoration-primary/60 underline-offset-4",
                o.w === "" && "line-through opacity-60",
              )}
            >
              {o.w || w.w}
            </button>
          );
        })}
      </p>
    </div>
  );
});
