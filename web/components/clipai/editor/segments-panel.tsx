"use client";

import { ArrowDown, ArrowUp, Copy, LogIn, LogOut, Scissors, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/clipai/editor/kbd";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BEST_LINE_ID, MIN_SEGMENT, type Segment, totalDuration } from "@/lib/edit-doc";
import { timecode } from "@/lib/format";
import type { ClipDTO } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props {
  clip: ClipDTO;
  segments: Segment[];
  selectedId: string | null;
  videoDuration: number;
  disabled: boolean;
  /** Rango permitido y lo que pidió la historia de este clip (null si no se sabe). */
  limits: { min: number; max: number; ideal: number | null };
  onSelect: (id: string) => void;
  onChange: (segments: Segment[], key?: string) => void;
  onSplit: () => void;
  onDuplicate: (id: string) => void;
  onMarkIn: () => void;
  onMarkOut: () => void;
  onSeek: (t: number) => void;
}

function TimeField({ value, label, onCommit, disabled }: {
  value: number; label: string; onCommit: (v: number) => void; disabled: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const parts = draft.trim().replace(",", ".").split(":").map(Number);
    const v = parts.reduce((acc, p) => acc * 60 + p, 0);
    if (parts.every(Number.isFinite) && v >= 0) onCommit(Math.round(v * 100) / 100);
    setDraft(null);
  };
  return (
    <input
      aria-label={label}
      disabled={disabled}
      value={draft ?? timecode(value, true)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setDraft(null);
      }}
      className="tabular h-7 w-[72px] rounded-md border border-input bg-transparent px-1.5 text-center text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
    />
  );
}

/** Tramos del clip en orden de reproducción. */
export function SegmentsPanel(p: Props) {
  const { segments, selectedId, disabled, limits, clip } = p;
  const total = totalDuration(segments);
  const inRange = total >= limits.min - 0.05 && total <= limits.max + 0.05;
  const hasBest = segments.some((s) => s.id === BEST_LINE_ID);
  const max = p.videoDuration > 0 ? p.videoDuration : Infinity;

  const update = (id: string, patch: Partial<Segment>) => p.onChange(segments.map((s) => {
    if (s.id !== id) return s;
    const next = { ...s, ...patch };
    next.start = Math.max(0, Math.min(next.start, next.end - MIN_SEGMENT));
    next.end = Math.min(max, Math.max(next.end, next.start + MIN_SEGMENT));
    return next;
  }));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= segments.length) return;
    const next = [...segments];
    [next[i], next[j]] = [next[j], next[i]];
    p.onChange(next);
  };

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm">
          Duración total{" "}
          <span className={cn("tabular font-semibold", inRange ? "text-success" : "text-primary")}>
            {total.toFixed(1)} s
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          Rango: {timecode(limits.min)}–{timecode(limits.max)}
          {limits.ideal ? ` · la historia pide ~${timecode(limits.ideal)}` : ""}
        </p>
      </div>

      <ol className="mt-3 space-y-1.5">
        {segments.map((s, i) => (
          <li
            key={s.id}
            className={cn(
              "flex flex-wrap items-center gap-2 rounded-lg border px-2 py-1.5",
              s.id === selectedId ? "border-primary bg-primary/10" : "border-border",
            )}
          >
            <button
              type="button"
              onClick={() => {
                p.onSelect(s.id);
                p.onSeek(s.start);
              }}
              className="font-condensed tabular grid size-7 shrink-0 place-items-center rounded-md bg-secondary text-sm font-bold outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={`Seleccionar el tramo ${i + 1}`}
            >
              {i + 1}
            </button>
            <TimeField label={`Inicio del tramo ${i + 1}`} value={s.start} disabled={disabled}
              onCommit={(v) => update(s.id, { start: v })} />
            <span className="text-xs text-muted-foreground">a</span>
            <TimeField label={`Fin del tramo ${i + 1}`} value={s.end} disabled={disabled}
              onCommit={(v) => update(s.id, { end: v })} />
            <span className="tabular w-12 text-xs text-muted-foreground">{(s.end - s.start).toFixed(1)} s</span>
            {s.id === BEST_LINE_ID && <span className="text-xs text-primary">frase más fuerte</span>}
            <span className="ml-auto flex gap-0.5">
              <Button variant="ghost" size="icon-xs" aria-label="Subir" disabled={disabled || i === 0} onClick={() => move(i, -1)}>
                <ArrowUp />
              </Button>
              <Button variant="ghost" size="icon-xs" aria-label="Bajar" disabled={disabled || i === segments.length - 1} onClick={() => move(i, 1)}>
                <ArrowDown />
              </Button>
              <Button variant="ghost" size="icon-xs" aria-label="Duplicar" disabled={disabled || segments.length >= 20} onClick={() => p.onDuplicate(s.id)}>
                <Copy />
              </Button>
              <Button variant="ghost" size="icon-xs" aria-label="Quitar" disabled={disabled || segments.length === 1}
                onClick={() => p.onChange(segments.filter((x) => x.id !== s.id))}>
                <Trash2 />
              </Button>
            </span>
          </li>
        ))}
      </ol>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" disabled={disabled} onClick={p.onSplit}>
          <Scissors /> Dividir en el cursor <Kbd>S</Kbd>
        </Button>
        <Button variant="secondary" size="sm" disabled={disabled || !selectedId} onClick={p.onMarkIn}>
          <LogIn /> Entrada <Kbd>I</Kbd>
        </Button>
        <Button variant="secondary" size="sm" disabled={disabled || !selectedId} onClick={p.onMarkOut}>
          <LogOut /> Salida <Kbd>O</Kbd>
        </Button>
      </div>

      {clip.bestLineStart != null && clip.bestLineEnd != null && (
        <div className="mt-4 flex items-start gap-3 rounded-lg bg-card p-3">
          <Switch
            id="prepend"
            checked={hasBest}
            disabled={disabled}
            onCheckedChange={(on) => p.onChange(on
              ? [{ id: BEST_LINE_ID, start: clip.bestLineStart!, end: clip.bestLineEnd! }, ...segments]
              : segments.filter((s) => s.id !== BEST_LINE_ID))}
          />
          <Label htmlFor="prepend" className="block text-sm leading-snug font-normal">
            Abrir con la frase más fuerte
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Antepone {(clip.bestLineEnd - clip.bestLineStart).toFixed(1)} s de «{clip.bestLine}» como avance
              (suma a la duración total).
            </span>
          </Label>
        </div>
      )}
    </div>
  );
}
