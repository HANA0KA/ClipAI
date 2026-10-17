import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { STATUS_LABEL } from "@/lib/format";
import type { ProjectDTO } from "@/lib/types";

// Semántica de cojeev: oliva = terminado, peligro = falló, ámbar suave = en curso, neutro = detenido.
const TONE: Record<string, "olive" | "danger" | "default" | "pink-soft"> = {
  READY: "olive",
  FAILED: "danger",
  PAUSED: "default",
  STOPPED: "default",
};

export function StatusBadge({ status }: { status: string }) {
  const variant = TONE[status] ?? "pink-soft";
  const live = variant === "pink-soft";
  return (
    <Badge variant={variant} className="gap-1.5">
      {live && <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-primary" />}
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}

// Las tres fases sí son una secuencia: descarga 0–20, transcripción 20–60, análisis 60–100.
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
