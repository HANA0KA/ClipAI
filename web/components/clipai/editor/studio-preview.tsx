"use client";

import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";
import {
  type AudioSettings, cssFilter, type Effects, type Framing, framingGeometry, outputSize, type Segment, segmentAt,
} from "@/lib/edit-doc";
import { cn } from "@/lib/utils";

export interface PreviewHandle {
  toggle: () => void;
  pause: () => void;
  seek: (t: number) => void;
  step: (dt: number) => void;
  time: () => number;
}

interface Props {
  /** false: la vista previa está oculta (se ve el render final) y debe callar. */
  active?: boolean;
  sourceUrl: string | null;
  segments: Segment[];
  framing: Framing;
  effects: Effects;
  audio: AudioSettings;
  loop: boolean;
  /** Tiempo del video fuente, ~15 veces por segundo. */
  onTime: (t: number) => void;
  onPlaying: (playing: boolean) => void;
  /** Arrastre del sujeto en encuadre manual (ancla 0–1). */
  onMove?: (x: number, y: number) => void;
  className?: string;
}

const ASPECT = { vertical: 9 / 16, square: 1 } as const;
/** Fondo desenfocado: el cuadro copiado a un lienzo diminuto (se estira y
 * difumina solo) unas 12 veces por segundo. Antes era un segundo <video> del
 * mismo archivo: el navegador decodificaba el video dos veces. */
const BG_W = 48;
const BG_EVERY_MS = 80;

/**
 * Vista previa del borrador sobre el video fuente: reproduce los tramos en su
 * orden (saltando entre ellos), con el encuadre manual y los efectos que
 * tendrá el render. En encuadre automático muestra el plano completo: el
 * recorte lo decide el reencuadre al renderizar.
 */
export const StudioPreview = forwardRef<PreviewHandle, Props>(function StudioPreview(
  { active = true, sourceUrl, segments, framing, effects, audio, loop, onTime, onPlaying, onMove, className },
  ref,
) {
  const box = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLVideoElement>(null);
  const back = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [natural, setNatural] = useState({ w: 16, h: 9 });
  const state = useRef({ segments, loop, index: 0, onTime, onPlaying, lastReport: 0, lastBg: 0, bgDirty: true });
  useEffect(() => {
    Object.assign(state.current, { segments, loop, onTime, onPlaying });
  });

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Bucle de reproducción: saltos entre tramos en el orden del clip.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = main.current;
      const st = state.current;
      if (v && !v.paused && st.segments.length) {
        const t = v.currentTime;
        let seg = st.segments[st.index];
        if (!seg || t < seg.start - 0.25 || t > seg.end + 0.25) {
          // Salto manual o fuera de todo tramo: se retoma en el tramo que toca.
          const inside = segmentAt(st.segments, t);
          if (inside >= 0) st.index = inside;
          else {
            const after = st.segments.map((s, i) => [s.start, i] as const).filter(([s]) => s > t)
              .sort((a, b) => a[0] - b[0])[0];
            st.index = after ? after[1] : 0;
            v.currentTime = st.segments[st.index].start;
          }
          seg = st.segments[st.index];
        } else if (t >= seg.end - 0.02) {
          if (st.index + 1 < st.segments.length) {
            st.index += 1;
            v.currentTime = st.segments[st.index].start;
          } else if (st.loop) {
            st.index = 0;
            v.currentTime = st.segments[0].start;
          } else {
            v.pause();
            v.currentTime = seg.end;
          }
        }
      }
      if (v) {
        const now = performance.now();
        if (now - st.lastReport > 66) {
          st.lastReport = now;
          st.onTime(v.currentTime);
        }
        const b = back.current;
        if (b && v.readyState >= 2 && (st.bgDirty || (!v.paused && now - st.lastBg > BG_EVERY_MS))) {
          st.lastBg = now;
          st.bgDirty = false;
          b.getContext("2d")?.drawImage(v, 0, 0, b.width, b.height);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const v = main.current;
    if (!v) return;
    v.volume = Math.min(1, audio.volume);
    v.muted = audio.muted || audio.volume === 0;
  }, [audio]);

  // Oculta (se ve el render final) o desmontada (otro clip, otra página): en
  // silencio. Un <video> oculto con CSS sigue sonando si nadie lo pausa.
  useEffect(() => {
    if (!active) main.current?.pause();
  }, [active]);
  useLayoutEffect(() => {
    const m = main.current;
    return () => m?.pause();
  }, []);

  useImperativeHandle(ref, () => ({
    toggle() {
      const v = main.current;
      if (!v) return;
      if (!v.paused) {
        v.pause();
        return;
      }
      const st = state.current;
      const t = v.currentTime;
      const i = segmentAt(st.segments, t);
      const atEnd = i === st.segments.length - 1 && i >= 0 && t >= st.segments[i].end - 0.05;
      const later = i < 0 && st.segments.some((s) => s.start > t);
      if (i >= 0 && !atEnd) st.index = i;
      else if (!later) {
        // Al final del clip (o después de todos los tramos): desde el principio.
        st.index = 0;
        v.currentTime = st.segments[0]?.start ?? 0;
      } // si hay un tramo más adelante, el bucle salta a él
      v.play().catch(() => {});
    },
    pause() {
      main.current?.pause();
    },
    seek(t: number) {
      const v = main.current;
      if (!v) return;
      v.currentTime = Math.max(0, t);
      const i = segmentAt(state.current.segments, t);
      if (i >= 0) state.current.index = i;
      state.current.onTime(v.currentTime);
    },
    step(dt: number) {
      const v = main.current;
      if (!v) return;
      v.pause();
      v.currentTime = Math.max(0, v.currentTime + dt);
      state.current.onTime(v.currentTime);
    },
    time: () => main.current?.currentTime ?? 0,
  }));

  const manual = framing.mode === "manual" || framing.aspect === "original";
  const ratio = framing.aspect === "original" ? natural.w / natural.h : ASPECT[framing.aspect];
  const out = outputSize(framing.aspect, natural.w, natural.h);
  const filter = cssFilter(effects, size.w / out.w);
  const g = manual && size.w > 0 ? framingGeometry(natural.w, natural.h, size.w, size.h, framing) : null;
  const drag = useRef<{ x: number; y: number; fx: number; fy: number } | null>(null);

  function onPointerDown(e: React.PointerEvent) {
    if (!g || !onMove) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, fx: framing.x, fy: framing.y };
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d || !g || !onMove) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    // Con el video más grande que el cuadro se mueve el recorte (al revés del
    // arrastre); con el video más chico se mueve el video dentro del cuadro.
    const nx = g.rw - g.cw > 1 ? d.fx - dx / (g.rw - g.cw) : size.w - g.cw > 1 ? d.fx + dx / (size.w - g.cw) : d.fx;
    const ny = g.rh - g.ch > 1 ? d.fy - dy / (g.rh - g.ch) : size.h - g.ch > 1 ? d.fy + dy / (size.h - g.ch) : d.fy;
    onMove(Math.min(1, Math.max(0, nx)), Math.min(1, Math.max(0, ny)));
  }

  return (
    <div
      ref={box}
      className={cn("relative w-full overflow-hidden rounded-xl bg-black select-none", g && onMove && "cursor-grab active:cursor-grabbing", className)}
      style={{ aspectRatio: String(ratio) }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={() => {
        drag.current = null;
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
    >
      {sourceUrl ? (
        <>
          {g && !g.fills && (
            <canvas
              ref={(el) => {
                back.current = el;
                if (el) state.current.bgDirty = true; // recién montado: pintarlo ya aunque esté en pausa
              }}
              width={BG_W}
              height={Math.max(1, Math.round((BG_W * natural.h) / natural.w))}
              aria-hidden
              className="absolute inset-0 size-full scale-110 object-cover"
              style={{ filter: `${filter} blur(${Math.max(6, size.w / 40)}px)` }}
            />
          )}
          <div
            className="absolute overflow-hidden"
            style={g ? { left: g.ox, top: g.oy, width: g.cw, height: g.ch } : { inset: 0 }}
          >
            <video
              ref={main}
              src={sourceUrl}
              playsInline
              preload="auto"
              className={cn("absolute max-w-none", !g && "size-full object-contain")}
              style={{ filter, ...(g ? { left: -g.cx, top: -g.cy, width: g.rw, height: g.rh } : {}) }}
              onLoadedMetadata={(e) => {
                const v = e.currentTarget;
                if (v.videoWidth && v.videoHeight) setNatural({ w: v.videoWidth, h: v.videoHeight });
                if (segments[0]) v.currentTime = segments[0].start;
              }}
              onPlay={() => state.current.onPlaying(true)}
              onPause={() => state.current.onPlaying(false)}
              onSeeked={() => {
                state.current.bgDirty = true;
              }}
              onLoadedData={() => {
                state.current.bgDirty = true;
              }}
            />
          </div>
          {!manual && (
            <span className="pointer-events-none absolute inset-x-0 bottom-2 mx-auto w-fit rounded-full bg-black/60 px-2.5 py-1 text-[11px] text-white/80">
              Encuadre automático: se calcula al renderizar
            </span>
          )}
        </>
      ) : (
        <div className="grid size-full place-items-center p-6 text-center text-sm text-muted-foreground">
          El video fuente se borró con «Limpiar»: solo puedes ver el render final.
        </div>
      )}
    </div>
  );
});
