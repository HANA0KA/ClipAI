"use client";

import { useSyncExternalStore } from "react";

/**
 * Tiempo de reproducción del estudio fuera del estado de React. La vista
 * previa lo actualiza ~15 veces por segundo; solo se redibujan los que lo
 * muestran (cabezal de la línea de tiempo, contador), no el estudio entero
 * con sus paneles, que antes se volvía a pintar en cada tic.
 */
export interface Playhead {
  get: () => number;
  set: (t: number) => void;
  subscribe: (listener: () => void) => () => void;
}

export function createPlayhead(initial = 0): Playhead {
  let time = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => time,
    set: (t: number) => {
      if (t === time) return;
      time = t;
      listeners.forEach((l) => l());
    },
    subscribe: (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

/** Segundo actual del video fuente (redibuja solo a quien lo usa). */
export function usePlayhead(playhead: Playhead): number {
  return useSyncExternalStore(playhead.subscribe, playhead.get, playhead.get);
}
