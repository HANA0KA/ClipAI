"use client";

import type { TemplateInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

const FONT: Record<string, string> = {
  "Montserrat ExtraBold": "var(--font-montserrat)",
  Anton: "var(--font-anton)",
};

/** Muestra cada plantilla con su fuente y sus colores reales. */
function Sample({ t }: { t: TemplateInfo }) {
  const words = t.id === "neon-anton" ? ["EL", "SECRETO"] : t.id === "clean-box" ? ["el", "secreto", "real"] : ["EL", "SECRETO", "REAL"];
  const active = 1;
  return (
    <span
      className="flex flex-wrap justify-center gap-x-1 text-[17px] leading-tight"
      style={{ fontFamily: FONT[t.font] ?? "inherit", fontWeight: t.font.includes("ExtraBold") ? 800 : 400 }}
    >
      {words.map((w, i) => (
        <span
          key={w}
          style={{
            color: i === active ? t.highlight : t.primary,
            // Contorno negro como el borde ASS de 5–6 px, sin -webkit-text-stroke
            // (deja artefactos en fuentes gruesas).
            textShadow: "1px 1px 0 #000, -1px 1px 0 #000, 1px -1px 0 #000, -1px -1px 0 #000, 0 2px 2px #000",
            background: i === active && t.id === "clean-box" ? "#7C3AED" : undefined,
            borderRadius: 3,
            padding: i === active && t.id === "clean-box" ? "0 3px" : undefined,
            filter: i === active && t.id === "neon-anton" ? `drop-shadow(0 0 4px ${t.highlight})` : undefined,
          }}
        >
          {w}
        </span>
      ))}
    </span>
  );
}

export function TemplatePicker({ templates, value, onChange }: { templates: TemplateInfo[]; value: string; onChange: (id: string) => void }) {
  return (
    <div role="radiogroup" aria-label="Plantilla de subtítulos" className="grid grid-cols-3 gap-2">
      {templates.map((t) => (
        <button
          key={t.id}
          type="button"
          role="radio"
          aria-checked={value === t.id}
          onClick={() => onChange(t.id)}
          title={t.description}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border bg-well px-1.5 pt-4 pb-2 outline-none focus-visible:ring-2 focus-visible:ring-ring",
            value === t.id ? "border-primary" : "border-border hover:border-muted-foreground/50",
          )}
        >
          <Sample t={t} />
          <span className={cn("text-xs", value === t.id ? "text-primary" : "text-muted-foreground")}>{t.name}</span>
        </button>
      ))}
    </div>
  );
}
