"use client";

import { AlertTriangle, Film, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { UseQueryResult } from "@tanstack/react-query";
import { duration as fmtDuration } from "@/lib/format";
import { formatClock } from "@/lib/sources";
import type { KickVodInfo, SourceInfo } from "@/lib/types";

const count = (n: number | null) => (n == null ? "" : n >= 1_000_000 ? `${(n / 1e6).toFixed(1).replace(".", ",")} M` : n >= 1000 ? `${Math.round(n / 1000)} mil` : String(n));

/** Estado del tramo elegido: segundos válidos o el motivo por el que no se puede crear aún. */
export interface RangeState {
  start: number | null;
  end: number | null;
  /** Mensaje que impide crear el proyecto (null = todo bien). */
  problem: string | null;
}

/** Valida el tramo contra lo que se sabe del VOD (duración y máximo de ClipAI). */
export function checkRange(start: number | null, end: number | null, raw: { from: string; to: string }, info: KickVodInfo | null): RangeState {
  const typed = raw.from.trim() !== "" || raw.to.trim() !== "";
  const maxSec = (info?.maxMinutes ?? 240) * 60;
  if (!typed) {
    return { start: null, end: null, problem: info?.tooLong
      ? `Este VOD dura ${fmtDuration(info.duration)}: elige un tramo de hasta ${info.maxMinutes} min (desde y hasta).` : null };
  }
  if (raw.to.trim() === "" || end == null) return { start: null, end: null, problem: "Escribe hasta dónde llega el tramo (por ejemplo 1:30:00)." };
  if ((raw.from.trim() !== "" && start == null)) return { start: null, end: null, problem: "No entiendo el inicio: usa 1:30:00, 90:00, 5400 o 1h30m." };
  const a = start ?? 0;
  if (end <= a) return { start: null, end: null, problem: "El fin del tramo debe quedar después del inicio." };
  if (end - a < 60) return { start: null, end: null, problem: "El tramo debe durar al menos 1 min (lo mínimo de un clip)." };
  if (end - a > maxSec) return { start: null, end: null, problem: `El tramo dura ${fmtDuration(end - a)}: el máximo es ${info?.maxMinutes ?? 240} min.` };
  if (info && a >= info.duration) return { start: null, end: null, problem: `El VOD dura ${fmtDuration(info.duration)}: el inicio queda fuera.` };
  return { start: a, end: info ? Math.min(end, info.duration) : end, problem: null };
}

function Vod({ info, thumbnail }: { info: KickVodInfo; thumbnail: string | null }) {
  const thumb = info.thumbnail ?? thumbnail;
  return (
    <div className="flex items-center gap-3">
      <div className="relative aspect-video w-32 shrink-0 overflow-hidden rounded-md bg-well">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="size-full object-cover" loading="lazy" referrerPolicy="no-referrer" />
        ) : <Film className="absolute inset-0 m-auto size-5 text-muted-foreground" />}
      </div>
      <div className="min-w-0 text-sm">
        <p className="line-clamp-2 font-medium">{info.title || "VOD de Kick"}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {info.channel} · {fmtDuration(info.duration)}{info.uploadedAt ? ` · ${info.uploadedAt}` : ""}{info.views ? ` · ${count(info.views)} vistas` : ""}
        </p>
      </div>
    </div>
  );
}

/**
 * Lo que aparece bajo el enlace cuando es de Kick: el VOD (o el aviso de que ya
 * no existe) y el tramo a usar. Los videos de un canal se ven en el panel de Kick.
 */
export function SourcePreview({ kind, query, from, to, onFrom, onTo, range, thumbnail }: {
  kind: "video" | "clip";
  query: UseQueryResult<SourceInfo>;
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
  range: RangeState;
  /** Miniatura que ya se vio en el panel de Kick (yt-dlp no siempre da una). */
  thumbnail: string | null;
}) {
  if (kind === "clip") {
    return <p className="mt-5 max-w-2xl text-sm text-destructive">Ese enlace es un clip de Kick (dura menos de un minuto). Pega el VOD: kick.com/canal/videos/…</p>;
  }
  const data = query.data;
  return (
    <div className="mt-5 max-w-2xl rounded-2xl border border-border bg-card p-4" aria-live="polite">
      {query.isFetching && !data ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Consultando Kick…</p>
      ) : query.error ? (
        <p className="flex items-start gap-2 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{(query.error as Error).message}</p>
      ) : data?.type === "kick" && data.kind === "video" ? (
        <div className="space-y-4">
          <Vod info={data} thumbnail={thumbnail} />
          {data.live && <p className="text-sm text-destructive">Ese VOD es de un directo en curso: espera a que termine.</p>}
          <div>
            <p className="mb-2 text-xs text-muted-foreground">
              Tramo a usar (opcional{data.tooLong ? ", necesario aquí" : ""}). Los directos duran horas: baja solo la parte que quieres convertir en
              clips, de 1 min a {data.maxMinutes} min. Se aceptan 1:30:00, 90:00, 5400 o 1h30m.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Input value={from} onChange={(e) => onFrom(e.target.value)} placeholder="Desde (0:00:00)" aria-label="Inicio del tramo" className="h-9 w-40" />
              <span aria-hidden className="text-muted-foreground">→</span>
              <Input value={to} onChange={(e) => onTo(e.target.value)} placeholder={`Hasta (${formatClock(Math.min(data.duration, 5400))})`} aria-label="Fin del tramo" className="h-9 w-40" />
              {range.start != null || range.end != null ? (
                <span className="tabular text-xs text-muted-foreground">
                  = {fmtDuration((range.end ?? 0) - (range.start ?? 0))} del VOD (los tiempos de los clips cuentan desde el inicio del tramo)
                </span>
              ) : null}
            </div>
            {range.problem && <p className="mt-2 text-xs text-destructive">{range.problem}</p>}
          </div>
        </div>
      ) : null}
    </div>
  );
}
