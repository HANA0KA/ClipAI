"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { cn } from "@/lib/utils";

export interface PlayerHandle {
  seek: (t: number) => void;
}

interface Props {
  mode: "final" | "original";
  finalUrl: string | null;
  posterUrl?: string | null;
  sourceUrl: string | null;
  start: number;
  end: number;
  className?: string;
}

/**
 * Visor 9:16. «final» reproduce el MP4 renderizado; «original» reproduce el
 * tramo [start, end] del video fuente en bucle, para revisar bordes y palabras
 * antes de volver a renderizar.
 */
export const VerticalPlayer = forwardRef<PlayerHandle, Props>(function VerticalPlayer(
  { mode, finalUrl, posterUrl, sourceUrl, start, end, className },
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const bounds = useRef({ start, end });
  bounds.current = { start, end };

  useImperativeHandle(ref, () => ({
    seek(t: number) {
      const v = video.current;
      if (!v) return;
      v.currentTime = mode === "original" ? t : Math.max(0, t - bounds.current.start);
      v.play().catch(() => {});
    },
  }));

  useEffect(() => {
    const v = video.current;
    if (v && mode === "original" && v.readyState > 0) v.currentTime = start;
  }, [start, mode]);

  const src = mode === "final" ? finalUrl : sourceUrl;
  return (
    <div className={cn("relative aspect-[9/16] w-full overflow-hidden rounded-xl bg-well", className)}>
      {src ? (
        <video
          key={src}
          ref={video}
          src={src}
          controls
          playsInline
          preload="metadata"
          poster={mode === "final" ? (posterUrl ?? undefined) : undefined}
          loop={mode === "final"}
          className={cn("size-full", mode === "final" ? "object-cover" : "object-contain")}
          onLoadedMetadata={(e) => {
            if (mode === "original") e.currentTarget.currentTime = bounds.current.start;
          }}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            if (mode === "original" && v.currentTime >= bounds.current.end) v.currentTime = bounds.current.start;
          }}
        />
      ) : (
        <div className="grid size-full place-items-center p-6 text-center text-sm text-muted-foreground">
          {mode === "final"
            ? "Aún no hay render. Guarda y renderiza para verlo en 9:16."
            : "El video fuente se borró con «Limpiar»."}
        </div>
      )}
    </div>
  );
});
