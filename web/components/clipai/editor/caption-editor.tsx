"use client";

import { useState } from "react";
import type { CaptionWord } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  words: CaptionWord[];
  start: number;
  end: number;
  edits: Record<number, string>;
  onEdit: (i: number, w: string) => void;
  onSeek: (t: number) => void;
}

/**
 * Palabras del clip. Un clic lleva el visor a esa palabra; doble clic la edita.
 * Solo cambia el texto: los tiempos se conservan (plan 6.2).
 */
export function CaptionEditor({ words, start, end, edits, onEdit, onSeek }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  if (!words.length) {
    return <p className="text-sm text-muted-foreground">No hay palabras para este tramo.</p>;
  }
  return (
    <p className="max-h-80 overflow-y-auto pr-2 text-[15px] leading-8">
      {words.map((w) => {
        const text = edits[w.i] ?? w.w;
        const inside = (w.start + w.end) / 2 >= start && (w.start + w.end) / 2 < end;
        if (editing === w.i) {
          return (
            <input
              key={w.i}
              autoFocus
              defaultValue={text}
              size={Math.max(2, text.length + 1)}
              aria-label="Corregir palabra"
              className="mx-0.5 rounded bg-muted px-1 text-foreground outline-none ring-2 ring-ring"
              onBlur={(e) => {
                if (e.target.value !== w.w || edits[w.i] !== undefined) onEdit(w.i, e.target.value);
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
            key={w.i}
            onClick={() => onSeek(w.start)}
            onDoubleClick={() => setEditing(w.i)}
            title="Clic: ir a esta palabra. Doble clic: corregir"
            className={cn(
              "mx-[1px] rounded px-0.5 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
              !inside && "text-muted-foreground/60",
              edits[w.i] !== undefined && "text-primary underline decoration-primary/60 underline-offset-4",
              text === "" && "line-through",
            )}
          >
            {text || w.w}
          </button>
        );
      })}
    </p>
  );
}
