"use client";

import { memo } from "react";
import type { TemplateInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Familia CSS para previsualizar una fuente de libass. */
export function cssFont(name: string | null | undefined): { fontFamily: string; fontWeight: number } {
  if (!name || name === "Montserrat ExtraBold") return { fontFamily: "var(--font-montserrat)", fontWeight: 800 };
  if (name === "Anton") return { fontFamily: "var(--font-anton)", fontWeight: 400 };
  return { fontFamily: `"${name}", var(--font-montserrat)`, fontWeight: 700 };
}

const OUTLINE = "1px 1px 0 #000, -1px 1px 0 #000, 1px -1px 0 #000, -1px -1px 0 #000, 0 2px 2px #000";

/** Muestra la plantilla con su fuente, colores, caja/franja y énfasis reales. */
function Sample({ t, font }: { t: TemplateInfo; font: string | null }) {
  const upper = t.uppercase ?? true;
  const words = ["el", "secreto", "real"].map((w) => (upper ? w.toUpperCase() : w));
  const active = 1;
  const emphasis = 2;
  const boxed = !!t.background;
  return (
    <span
      className="flex flex-wrap justify-center gap-x-1 px-1 text-[16px] leading-tight"
      style={{
        ...cssFont(font ?? t.font),
        background: boxed ? `${t.background}B3` : undefined,
        borderRadius: 3,
        padding: boxed ? "2px 5px" : undefined,
      }}
    >
      {words.map((w, i) => (
        <span
          key={w}
          style={{
            color: i === active ? t.highlight : i === emphasis && t.emphasis ? t.emphasis : t.primary,
            // Contorno negro como el borde ASS (sin -webkit-text-stroke: deja
            // artefactos en fuentes gruesas). Las plantillas con franja no lo llevan.
            textShadow: boxed ? undefined : OUTLINE,
            background: i === active && t.animation === "box" ? t.box_color ?? undefined : undefined,
            borderRadius: 3,
            padding: i === active && t.animation === "box" ? "0 3px" : undefined,
            filter: i === active && t.animation === "glow" ? `drop-shadow(0 0 4px ${t.highlight})` : undefined,
          }}
        >
          {w}
        </span>
      ))}
    </span>
  );
}

export const TemplatePicker = memo(function TemplatePicker({ templates, value, font, projectTemplate, onChange }: {
  templates: TemplateInfo[]; value: string; font: string | null; onChange: (id: string) => void;
  /** Plantilla del proyecto (la de todos sus clips salvo que cambies una). */
  projectTemplate?: string | null;
}) {
  return (
    <div role="radiogroup" aria-label="Plantilla de subtítulos" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {templates.map((t) => (
        <button
          key={t.id}
          type="button"
          role="radio"
          aria-checked={value === t.id}
          onClick={() => onChange(t.id)}
          title={t.description}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border bg-well px-1 pt-4 pb-2 outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === t.id ? "border-primary" : "border-border hover:border-muted-foreground/50",
          )}
        >
          <Sample t={t} font={font} />
          <span className={cn("text-xs", value === t.id ? "text-primary" : "text-muted-foreground")}>
            {t.name}
            {t.emoji ? " · emojis" : ""}
          </span>
          {projectTemplate === t.id && (
            <span className="-mt-1 text-[10px] text-muted-foreground" title="La plantilla de este proyecto">del proyecto</span>
          )}
        </button>
      ))}
    </div>
  );
});
