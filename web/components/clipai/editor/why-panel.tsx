import type { ClipDTO } from "@/lib/types";
import { ScoreBadge } from "../clip-card";

const AXES: { key: "hook" | "story" | "value" | "engagement" | "reach"; label: string }[] = [
  { key: "hook", label: "Gancho" },
  { key: "story", label: "Historia" },
  { key: "value", label: "Valor" },
  { key: "engagement", label: "Interacción" },
  { key: "reach", label: "Alcance" },
];

function Bar({ label, value, max }: { label: string; value: number | null | undefined; max: number }) {
  const v = value ?? 0;
  return (
    <div className="grid grid-cols-[88px_1fr_32px] items-center gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${(v / max) * 100}%` }} />
      </div>
      <span className="tabular text-right">{value == null ? "–" : max === 10 ? v : Math.round(v * 100)}</span>
    </div>
  );
}

/** Por qué se eligió este clip: razón, ejes del juez y señales objetivas. */
export function WhyPanel({ clip }: { clip: ClipDTO }) {
  const s = clip.signals;
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <ScoreBadge score={clip.score} />
        <p className="text-sm leading-relaxed text-foreground/90">{clip.reason}</p>
      </div>
      {s.judge && (
        <div className="space-y-1.5">
          {AXES.map((a) => (
            <Bar key={a.key} label={a.label} value={s.judge?.[a.key]} max={10} />
          ))}
        </div>
      )}
      <div className="space-y-1.5">
        <Bar label="Heatmap" value={s.heat} max={1} />
        <Bar label="Audio" value={s.audio} max={1} />
        <Bar label="Densidad" value={s.density} max={1} />
        <Bar label="Gancho (texto)" value={s.hook} max={1} />
      </div>
      {clip.bestLine && <blockquote className="border-l-2 border-primary pl-3 text-sm italic">«{clip.bestLine}»</blockquote>}
    </div>
  );
}
