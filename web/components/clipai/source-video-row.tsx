"use client";

import { Film } from "lucide-react";
import { cn } from "@/lib/utils";

/** 1 200 000 → «1,2 M», 413 000 → «413 mil». */
export const count = (n: number | null) =>
  n == null ? "" : n >= 1_000_000 ? `${(n / 1e6).toFixed(1).replace(".0", "").replace(".", ",")} M` : n >= 1000 ? `${Math.round(n / 1000)} mil` : String(n);

/** Marca de Kick: el bloque verde con la K. Es el único sitio donde aparece su color. */
export function KickMark({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn("grid size-5 shrink-0 place-items-center rounded-[4px] bg-[#53fc18] text-[13px] leading-none font-black text-black", className)}>
      K
    </span>
  );
}

/** Marca de YouTube: el rectángulo rojo con el triángulo. Solo aparece aquí. */
export function YoutubeMark({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn("grid h-4 w-[22px] shrink-0 place-items-center rounded-[5px] bg-[#ff0033]", className)}>
      <svg viewBox="0 0 10 10" className="size-2 fill-white"><path d="M2 1l7 4-7 4z" /></svg>
    </span>
  );
}

/**
 * Un video de un streamer o canal: miniatura 16:9 con la duración encima. Al elegirlo aparece sobre el
 * cuadro la ventana vertical 9:16 (ámbar, con el resto atenuado): lo que ClipAI va a recortar de este
 * video. `blocked` explica por qué no se puede elegir (directo en curso, demasiado largo…).
 */
export function VideoRow({ title, thumbnail, badge, left, right, selected, blocked, onPick }: {
  title: string;
  thumbnail: string | null;
  /** Texto sobre la miniatura (duración, «En vivo»). */
  badge: string;
  left?: string;
  right?: string;
  selected: boolean;
  blocked?: string | null;
  onPick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        disabled={!!blocked}
        aria-pressed={selected}
        title={blocked ?? undefined}
        className={cn(
          "group grid w-full grid-cols-[136px_minmax(0,1fr)] gap-3 rounded-[var(--r-card-sm)] border p-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-55",
          selected ? "border-primary bg-[var(--v-pink-soft)]" : "border-transparent hover:bg-[var(--v-beige)]",
        )}
      >
        <span className="relative block aspect-video overflow-hidden rounded-[var(--r-md)] bg-well">
          {thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" className="size-full object-cover" />
          ) : (
            <Film className="absolute inset-0 m-auto size-5 text-muted-foreground" />
          )}
          {/* Ventana 9:16 sobre un cuadro 16:9: ancho = (9/16)/(16/9) ≈ 31,6 % */}
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-y-0 left-1/2 w-[31.6%] -translate-x-1/2 origin-center border-x-2 border-primary shadow-[0_0_0_100vmax_rgb(20_22_27/0.62)] transition-[opacity,transform] duration-300 ease-out",
              selected ? "scale-x-100 opacity-100" : "scale-x-50 opacity-0 group-hover:scale-x-100 group-hover:opacity-60",
            )}
          />
          <span className="tabular absolute right-1 bottom-1 rounded-full bg-black/80 px-1.5 py-px text-[11px] font-medium text-white">{badge}</span>
        </span>
        <span className="flex min-w-0 flex-col justify-between py-0.5">
          <span className="line-clamp-2 text-sm leading-snug font-medium">{title || "Sin título"}</span>
          <span className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
            <span>{left}</span>
            {right ? <span className="tabular">{right}</span> : null}
          </span>
        </span>
      </button>
    </li>
  );
}
