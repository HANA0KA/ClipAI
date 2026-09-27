"use client";

import { Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { timecode } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  start: number;
  end: number;
  videoDuration: number;
  onChange: (start: number, end: number) => void;
  disabled?: boolean;
}

const CONTEXT = 30; // segundos visibles a cada lado del clip
const round = (x: number) => Math.round(x * 10) / 10;

function Nudge({ label, value, onChange, disabled }: { label: string; value: number; onChange: (v: number) => void; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-1">
      <span className="w-12 text-xs text-muted-foreground">{label}</span>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`${label} −0,5 s`} disabled={disabled} onClick={() => onChange(round(value - 0.5))}>
        <Minus />
      </Button>
      <span className="tabular w-16 text-center text-sm">{timecode(value, true)}</span>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={`${label} +0,5 s`} disabled={disabled} onClick={() => onChange(round(value + 0.5))}>
        <Plus />
      </Button>
    </div>
  );
}

/** Bordes del clip: deslizador con contexto de ±30 s y ajustes finos de medio segundo. */
export function BoundsEditor({ start, end, videoDuration, onChange, disabled }: Props) {
  const lo = Math.max(0, Math.floor(start - CONTEXT));
  const hi = Math.min(videoDuration || end + CONTEXT, Math.ceil(end + CONTEXT));
  const dur = end - start;
  const outOfRange = dur < 30 || dur > 90;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="tabular text-xs text-muted-foreground">{timecode(lo)}</span>
        <span className={cn("tabular text-sm font-semibold", outOfRange ? "text-primary" : "text-foreground")}>
          {dur.toFixed(1)} s{outOfRange ? " (lo ideal es 30 a 90 s)" : ""}
        </span>
        <span className="tabular text-xs text-muted-foreground">{timecode(hi)}</span>
      </div>
      <Slider
        className="mt-3"
        min={lo}
        max={hi}
        step={0.1}
        value={[start, end]}
        minStepsBetweenThumbs={30}
        disabled={disabled}
        onValueChange={([s, e]) => onChange(round(s), round(e))}
        aria-label="Inicio y fin del clip"
      />
      <div className="mt-3 flex flex-wrap justify-between gap-2">
        <Nudge label="Inicio" value={start} disabled={disabled} onChange={(v) => v >= 0 && v < end - 3 && onChange(v, end)} />
        <Nudge label="Fin" value={end} disabled={disabled} onChange={(v) => v > start + 3 && (!videoDuration || v <= videoDuration) && onChange(start, v)} />
      </div>
    </div>
  );
}
