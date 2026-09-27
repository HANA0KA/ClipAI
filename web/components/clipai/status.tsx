import { cn } from "@/lib/utils";
import { STATUS_LABEL } from "@/lib/format";
import type { ProjectDTO } from "@/lib/types";

const TONE: Record<string, string> = {
  READY: "text-success border-success/40",
  FAILED: "text-destructive border-destructive/40",
  PAUSED: "text-muted-foreground border-border",
  STOPPED: "text-muted-foreground border-border",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-xs", TONE[status] ?? "text-primary border-primary/40")}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// Las tres fases sí son una secuencia (plan 5): descarga 0–20, transcripción 20–60, análisis 60–100.
const PHASES = [
  { key: "DOWNLOADING", label: "Descarga", from: 0, to: 20 },
  { key: "TRANSCRIBING", label: "Transcripción", from: 20, to: 60 },
  { key: "ANALYZING", label: "Momentos", from: 60, to: 100 },
];

export function PhaseBar({ project, compact = false }: { project: ProjectDTO; compact?: boolean }) {
  const p = project.status === "READY" ? 100 : project.progress;
  return (
    <div className="w-full">
      <div className="flex gap-1" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100}>
        {PHASES.map((ph) => {
          const fill = Math.max(0, Math.min(1, (p - ph.from) / (ph.to - ph.from)));
          return (
            <div key={ph.key} className="flex-1" style={{ flexGrow: ph.to - ph.from }}>
              <div className={cn("h-1.5 overflow-hidden rounded-full bg-muted", compact && "h-1")}>
                <div className="h-full rounded-full bg-primary transition-[width] duration-700" style={{ width: `${fill * 100}%` }} />
              </div>
              {!compact && (
                <span className={cn("mt-1.5 block text-xs", fill > 0 ? "text-foreground" : "text-muted-foreground")}>
                  {ph.label}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
