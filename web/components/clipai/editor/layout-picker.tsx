"use client";

import type { LayoutMode } from "@/lib/types";
import { cn } from "@/lib/utils";

const OPTIONS: { value: LayoutMode; label: string; hint: string; glyph: React.ReactNode }[] = [
  { value: "auto", label: "Automático", hint: "Elige el mejor diseño en cada escena y sigue a quien se mueve", glyph: <span className="text-[10px] font-bold">A</span> },
  {
    value: "track", label: "Una persona", hint: "Recorte sobre el rostro que habla; si camina, la cámara lo sigue",
    glyph: <span className="size-2.5 rounded-full bg-current" />,
  },
  {
    value: "split", label: "Dos personas", hint: "Una arriba y otra abajo; subtítulos en la unión",
    glyph: (
      <span className="flex flex-col gap-0.5">
        <span className="size-2 rounded-full bg-current" />
        <span className="size-2 rounded-full bg-current" />
      </span>
    ),
  },
  {
    value: "wide", label: "Plano abierto", hint: "Recorte amplio y fijo que deja a todos dentro",
    glyph: (
      <span className="flex gap-0.5">
        <span className="size-1.5 rounded-full bg-current" />
        <span className="size-1.5 rounded-full bg-current" />
        <span className="size-1.5 rounded-full bg-current" />
      </span>
    ),
  },
  {
    value: "off", label: "Sin recorte", hint: "Video completo sobre fondo desenfocado",
    glyph: <span className="h-2 w-3.5 rounded-[2px] bg-current" />,
  },
];

export function LayoutPicker({ value, onChange, disabled }: { value: LayoutMode; onChange: (v: LayoutMode) => void; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label="Diseño de encuadre" className="grid gap-1.5">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn(
            "flex items-center gap-3 rounded-lg border px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
            value === o.value ? "border-primary bg-primary/10" : "border-border hover:bg-accent",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "grid h-8 w-[18px] shrink-0 place-items-center rounded-[3px] border",
              value === o.value ? "border-primary text-primary" : "border-muted-foreground/60 text-muted-foreground",
            )}
          >
            {o.glyph}
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium">{o.label}</span>
            <span className="block truncate text-xs text-muted-foreground">{o.hint}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
