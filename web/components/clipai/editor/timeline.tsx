"use client";

import { Loader2 } from "lucide-react";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTimeline } from "@/lib/client";
import { MIN_SEGMENT, type Segment } from "@/lib/edit-doc";
import { timecode } from "@/lib/format";
import { cn } from "@/lib/utils";
import { type Playhead, usePlayhead } from "./playhead";

interface Props {
  clipId: string;
  videoDuration: number;
  segments: Segment[];
  selectedId: string | null;
  /** Tiempo de reproducción (solo el cabezal se redibuja con él). */
  playhead: Playhead;
  disabled?: boolean;
  onSeek: (t: number) => void;
  onSelect: (id: string) => void;
  /** Cambio de bordes al arrastrar (``key`` agrupa el arrastre en un solo paso de deshacer). */
  onChange: (id: string, start: number, end: number, key: string) => void;
}

const TRACK_H = 56;
const LANE_H = 22;

/** Rango visible: los tramos con margen, redondeado a 10 s para no pedir
 * miniaturas nuevas en cada arrastre. */
function viewRange(segments: Segment[], duration: number): [number, number] {
  const lo = Math.min(...segments.map((s) => s.start));
  const hi = Math.max(...segments.map((s) => s.end));
  const pad = Math.max(6, (hi - lo) * 0.12);
  const a = Math.max(0, Math.floor((lo - pad) / 10) * 10);
  const b = Math.ceil((hi + pad) / 10) * 10;
  return [a, duration > 0 ? Math.min(Math.max(b, a + 10), Math.ceil(duration)) : b];
}

/** Carriles para tramos que se solapan (p. ej. un duplicado). */
function lanes(segments: Segment[]): Map<string, number> {
  const out = new Map<string, number>();
  const ends: number[] = [];
  for (const s of [...segments].sort((a, b) => a.start - b.start)) {
    let lane = ends.findIndex((e) => e <= s.start + 1e-3);
    if (lane < 0) lane = ends.length;
    ends[lane] = s.end;
    out.set(s.id, lane);
  }
  return out;
}

/** Cabezal: lo único que cambia con la reproducción. */
function PlayheadLine({ playhead, a, span, width }: { playhead: Playhead; a: number; span: number; width: number }) {
  const px = ((usePlayhead(playhead) - a) / span) * width;
  if (!(px >= 0 && px <= width)) return null;
  return <span aria-hidden className="pointer-events-none absolute top-0 bottom-0 z-20 w-0.5 bg-white" style={{ left: px }} />;
}

export const Timeline = memo(function Timeline({
  clipId, videoDuration, segments, selectedId, playhead, disabled, onSeek, onSelect, onChange,
}: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [a, b] = useMemo(() => viewRange(segments, videoDuration), [segments, videoDuration]);
  // Mientras arrastras, las miniaturas siguen siendo las del rango de antes
  // (sin pedir tiras nuevas a ffmpeg a mitad del gesto); al soltar se piden.
  const [frozen, setFrozen] = useState<[number, number] | null>(null);
  const assets = useTimeline(clipId, frozen?.[0] ?? a, frozen?.[1] ?? b, !disabled);
  const laneOf = useMemo(() => lanes(segments), [segments]);
  const nLanes = Math.max(1, ...[...laneOf.values()].map((l) => l + 1));
  const span = Math.max(1e-6, b - a);
  const x = (t: number) => ((t - a) / span) * width;
  const tAt = (px: number) => a + (px / Math.max(1, width)) * span;

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Forma de onda (sobre el rango que devolvió el servidor).
  const data = assets.data;
  useEffect(() => {
    const c = canvas.current;
    if (!c || !width) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(width * dpr);
    c.height = Math.round(TRACK_H * dpr);
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, TRACK_H);
    if (!data?.peaks.length) return;
    const x0 = ((data.start - a) / span) * width;
    const w = ((data.end - data.start) / span) * width;
    const step = w / data.peaks.length;
    ctx.fillStyle = "rgba(242, 180, 65, 0.85)";
    const mid = TRACK_H - 14;
    data.peaks.forEach((p, i) => {
      const h = Math.max(1, p * 12);
      ctx.fillRect(x0 + i * step, mid - h, Math.max(1, step - 0.5), h * 2);
    });
  }, [data, width, a, span]);

  const drag = useRef<{
    id: string; side: "start" | "end" | "move"; x0: number; s0: number; e0: number; moved: boolean; x: number;
    frame: number; last: [number, number] | null;
  } | null>(null);
  // Lo último de cada render, para aplicar el arrastre en el siguiente cuadro.
  const latest = useRef({ width, span, videoDuration, onChange, onSeek });
  useEffect(() => {
    latest.current = { width, span, videoDuration, onChange, onSeek };
  });
  useEffect(() => () => cancelAnimationFrame(drag.current?.frame ?? 0), []);

  function startDrag(e: React.PointerEvent, seg: Segment, side: "start" | "end" | "move") {
    if (disabled) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { id: seg.id, side, x0: e.clientX, s0: seg.start, e0: seg.end, moved: false, x: e.clientX, frame: 0, last: null };
    setFrozen([a, b]);
    onSelect(seg.id);
  }

  /** Un cambio por cuadro como mucho: el puntero manda decenas de eventos
   * por cuadro y cada uno era un cambio de estado + un salto del video. */
  function applyDrag() {
    const d = drag.current;
    if (!d) return;
    d.frame = 0;
    const { width: w, span: sp, videoDuration: dur, onChange: change, onSeek: seek } = latest.current;
    const dt = ((d.x - d.x0) / Math.max(1, w)) * sp;
    const max = dur > 0 ? dur : Infinity;
    const r = (v: number) => Math.round(v * 20) / 20; // pasos de 0,05 s
    let s = d.s0;
    let en = d.e0;
    if (d.side === "start") s = Math.min(d.e0 - MIN_SEGMENT, Math.max(0, r(d.s0 + dt)));
    else if (d.side === "end") en = Math.max(d.s0 + MIN_SEGMENT, Math.min(max, r(d.e0 + dt)));
    else {
      const len = d.e0 - d.s0;
      s = Math.min(max - len, Math.max(0, r(d.s0 + dt)));
      en = s + len;
    }
    if (d.last && d.last[0] === s && d.last[1] === en) return; // mismo paso de 0,05 s: nada que hacer
    d.last = [s, en];
    change(d.id, s, en, `drag-${d.id}-${d.side}`);
    seek(d.side === "end" ? en : s);
  }

  function moveDrag(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    d.x = e.clientX;
    if (Math.abs(e.clientX - d.x0) > 2) d.moved = true;
    if (!d.frame) d.frame = requestAnimationFrame(applyDrag);
  }

  function endDrag(e: React.PointerEvent) {
    const d = drag.current;
    if (d?.frame) {
      cancelAnimationFrame(d.frame);
      d.x = e.clientX;
      applyDrag(); // la posición final exacta
    }
    drag.current = null;
    setFrozen(null);
    if (d && !d.moved && d.side === "move") onSeek(tAt(e.clientX - (wrap.current?.getBoundingClientRect().left ?? 0)));
  }

  function cancelDrag() {
    cancelAnimationFrame(drag.current?.frame ?? 0);
    drag.current = null;
    setFrozen(null);
  }

  const ticks = useMemo(() => {
    const stepT = span > 240 ? 30 : span > 120 ? 20 : span > 50 ? 10 : 5;
    const out: number[] = [];
    for (let t = Math.ceil(a / stepT) * stepT; t <= b; t += stepT) out.push(t);
    return out;
  }, [a, b, span]);

  const order = new Map(segments.map((s, i) => [s.id, i + 1]));

  return (
    <div className="select-none">
      <div
        ref={wrap}
        className={cn("relative overflow-hidden rounded-lg bg-well", disabled ? "opacity-60" : "cursor-pointer")}
        style={{ height: TRACK_H + nLanes * LANE_H + 18 }}
        onPointerDown={(e) => {
          if (disabled || e.target !== e.currentTarget) return;
          onSeek(tAt(e.clientX - e.currentTarget.getBoundingClientRect().left));
        }}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={cancelDrag}
        role="group"
        aria-label="Línea de tiempo del video fuente"
      >
        {/* Miniaturas */}
        {data && (
          <div
            aria-hidden
            className="pointer-events-none absolute top-0 opacity-70"
            style={{
              left: x(data.start), width: x(data.end) - x(data.start), height: TRACK_H,
              backgroundImage: `url(${data.thumbs})`, backgroundSize: "100% 100%",
            }}
          />
        )}
        <canvas ref={canvas} aria-hidden className="pointer-events-none absolute top-0 left-0" style={{ width, height: TRACK_H }} />
        {assets.isFetching && (
          <Loader2 className="pointer-events-none absolute top-2 right-2 size-4 animate-spin text-muted-foreground" />
        )}
        {assets.isError && (
          <span className="pointer-events-none absolute top-2 left-2 text-xs text-muted-foreground">
            {(assets.error as Error).message}
          </span>
        )}

        {/* Tramos */}
        {segments.map((s) => {
          const left = x(s.start);
          const w = Math.max(6, x(s.end) - left);
          const lane = laneOf.get(s.id) ?? 0;
          const sel = s.id === selectedId;
          return (
            <div
              key={s.id}
              className={cn(
                "absolute flex items-center justify-center rounded-md border text-[11px] font-semibold",
                sel ? "z-10 border-primary bg-primary/35 text-primary-foreground" : "border-primary/50 bg-primary/15 text-foreground",
                !disabled && "cursor-grab active:cursor-grabbing",
              )}
              style={{ left, width: w, top: TRACK_H + 2 + lane * LANE_H, height: LANE_H - 4 }}
              onPointerDown={(e) => startDrag(e, s, "move")}
              title={`Tramo ${order.get(s.id)}: ${timecode(s.start, true)} a ${timecode(s.end, true)}`}
            >
              <span className="pointer-events-none truncate px-2">{order.get(s.id)}</span>
              {!disabled && (
                <>
                  {/* Asas (con teclado: campos de la pestaña Tramos, I y O) */}
                  <span
                    aria-hidden
                    title="Arrastra para mover el inicio"
                    className="absolute inset-y-0 left-0 w-2 cursor-ew-resize rounded-l-md bg-primary"
                    onPointerDown={(e) => startDrag(e, s, "start")}
                  />
                  <span
                    aria-hidden
                    title="Arrastra para mover el fin"
                    className="absolute inset-y-0 right-0 w-2 cursor-ew-resize rounded-r-md bg-primary"
                    onPointerDown={(e) => startDrag(e, s, "end")}
                  />
                </>
              )}
              {/* Sombreado del tramo sobre las miniaturas */}
              <span
                aria-hidden
                className={cn("pointer-events-none absolute left-0 w-full border-x", sel ? "border-primary bg-primary/10" : "border-primary/30")}
                style={{ top: -(TRACK_H + 3 + lane * LANE_H), height: TRACK_H }}
              />
            </div>
          );
        })}

        {/* Regla */}
        {ticks.map((t) => (
          <span
            key={t}
            className="tabular pointer-events-none absolute bottom-0.5 -translate-x-1/2 text-[10px] text-muted-foreground"
            style={{ left: x(t) }}
          >
            {timecode(t)}
          </span>
        ))}

        {/* Cabezal */}
        <PlayheadLine playhead={playhead} a={a} span={span} width={width} />
      </div>
    </div>
  );
});
