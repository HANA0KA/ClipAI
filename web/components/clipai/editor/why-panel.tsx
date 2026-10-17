import { HOOK_TYPE_LABEL } from "@/lib/hook";
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
      {clip.hookType && HOOK_TYPE_LABEL[clip.hookType] && (
        <p className="text-xs text-muted-foreground">
          Tipo de gancho: <span className="font-medium text-foreground">{HOOK_TYPE_LABEL[clip.hookType]}</span>
        </p>
      )}
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
        {s.pause != null && <Bar label="Pausa previa" value={s.pause} max={1} />}
      </div>
      {clip.bestLine && <blockquote className="border-l-2 border-primary pl-3 text-sm italic">«{clip.bestLine}»</blockquote>}
      {s.arc && (s.arc.hook || s.arc.payoff || s.arc.source === "heuristic") && (
        <div className="space-y-1.5 rounded-lg bg-card p-3 text-xs">
          <p className="font-semibold text-foreground">
            Estructura{s.arc.duration ? ` · ${Math.round(s.arc.duration)} s` : ""}
            {s.arc.cold_open ? " · abre con un avance" : ""}
          </p>
          {s.arc.hook && <p><span className="text-muted-foreground">Gancho:</span> «{s.arc.hook}»</p>}
          {s.arc.context && <p><span className="text-muted-foreground">Contexto:</span> {s.arc.context}</p>}
          {s.arc.payoff && <p><span className="text-muted-foreground">Remate:</span> «{s.arc.payoff}»</p>}
          {s.arc.reason && <p className="text-muted-foreground">{s.arc.reason}</p>}
          {s.arc.source === "heuristic" && (
            <p className="text-muted-foreground">Sin IA: termina donde cambia el tema o hay una pausa larga.</p>
          )}
        </div>
      )}
    </div>
  );
}
