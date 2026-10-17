"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/client";
import type { AudioSettings, Effects, Framing, Preset, Segment } from "@/lib/edit-doc";
import type { ClipDetail, LayoutMode, OriginalSnapshot } from "@/lib/types";

export interface WordOverride {
  w: string;
  hl: boolean;
}

/** Todo lo editable del clip. Las palabras van por clave = inicio en ms. */
export interface StudioState {
  segments: Segment[];
  framing: Framing;
  effects: Effects;
  audio: AudioSettings;
  preset: Preset;
  font: string | null;
  punch: boolean;
  hookSeconds: number | null;
  hook: string; // gancho con emoji: título, descripción, portada y nombre de los archivos
  hashtags: string;
  templateId: string;
  layoutMode: LayoutMode;
  smartCut: boolean;
  words: Record<string, WordOverride>;
}

export type SaveStatus = "saved" | "pending" | "saving" | "error" | "conflict";

interface Model {
  cur: StudioState;
  past: StudioState[];
  future: StudioState[];
  saved: StudioState; // lo que tiene el servidor
  revision: number;
}

const HISTORY = 100;
const AUTOSAVE_MS = 1200;
const COALESCE_MS = 800;

export const wordKey = (t: number) => String(Math.round(t * 1000));

export function stateFromDetail(d: ClipDetail): StudioState {
  const c = d.clip;
  return {
    segments: d.doc.segments,
    framing: d.doc.framing,
    effects: d.doc.effects,
    audio: d.doc.audio,
    preset: d.doc.preset,
    font: d.doc.font,
    punch: d.doc.punch,
    hookSeconds: d.doc.hookSeconds,
    hook: c.hook,
    hashtags: c.hashtags,
    templateId: c.templateId,
    layoutMode: c.layoutMode,
    smartCut: c.smartCut,
    words: Object.fromEntries(d.captions.words.map((w) => [wordKey(w.t), { w: w.w, hl: w.hl }])),
  };
}

/** Estado de «Restaurar original»: lo que no guarda el original (encuadre,
 * efectos…) vuelve a sus valores por defecto. */
export function stateFromOriginal(o: OriginalSnapshot, cur: StudioState, defaults: Pick<StudioState,
  "framing" | "effects" | "audio" | "preset" | "font" | "punch" | "hookSeconds">): StudioState {
  const words = { ...cur.words };
  for (const w of o.words) {
    const k = wordKey(w.t);
    if (k in words) words[k] = { w: w.w, hl: w.hl };
  }
  return {
    ...cur, ...defaults,
    segments: o.segments, hook: o.hook, hashtags: o.hashtags,
    templateId: o.templateId, layoutMode: o.layoutMode, smartCut: o.smartCut, words,
  };
}

const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b);

/** Igualdad del borrador clave por clave: lo que no cambió conserva su
 * referencia y no se serializa (las palabras son cientos de entradas y esto
 * corre en cada cambio, p. ej. en cada cuadro de un arrastre). */
function sameState(a: StudioState, b: StudioState): boolean {
  if (a === b) return true;
  return (Object.keys(a) as (keyof StudioState)[]).every((k) => same(a[k], b[k]));
}

function buildPatch(saved: StudioState, cur: StudioState, revision: number) {
  const body: Record<string, unknown> = { revision };
  const docKeys = ["segments", "framing", "effects", "audio", "preset", "font", "punch", "hookSeconds"] as const;
  if (docKeys.some((k) => !same(saved[k], cur[k]))) {
    body.doc = Object.fromEntries(docKeys.map((k) => [k, cur[k]]));
  }
  for (const k of ["hook", "hashtags", "templateId", "layoutMode", "smartCut"] as const) {
    if (!same(saved[k], cur[k])) body[k] = cur[k];
  }
  const words = cur.words === saved.words ? [] : Object.entries(cur.words)
    .filter(([k, v]) => saved.words[k]?.w !== v.w || saved.words[k]?.hl !== v.hl)
    .map(([k, v]) => ({ t: Number(k) / 1000, w: v.w, hl: v.hl }));
  if (words.length) body.words = words;
  return body;
}

/**
 * Borrador del estudio: historial para deshacer/rehacer, autoguardado a los
 * 1,2 s sin cambios (un guardado a la vez, cada uno con la revisión que
 * devolvió el anterior) y detección de ediciones desde otra pestaña (409).
 */
export function useStudio(clipId: string, detail: ClipDetail | undefined) {
  const qc = useQueryClient();
  const [model, setModel] = useState<Model | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [status, setStatus] = useState<SaveStatus>("saved");
  const [error, setError] = useState<string | null>(null);

  // Se inicializa una vez por clip (el sondeo del render no pisa lo que editas).
  if (detail && loadedFor !== detail.clip.id) {
    setLoadedFor(detail.clip.id);
    const s = stateFromDetail(detail);
    setModel({ cur: s, past: [], future: [], saved: s, revision: detail.clip.editRevision });
    setStatus("saved");
    setError(null);
  }

  const modelRef = useRef<Model | null>(model);
  const statusRef = useRef<SaveStatus>(status);
  useEffect(() => {
    modelRef.current = model;
    statusRef.current = status;
  });
  const coalesce = useRef<{ key: string; at: number } | null>(null);
  const inflight = useRef<Promise<boolean> | null>(null);
  const failed = useRef<StudioState | null>(null); // no reintentar lo mismo que ya falló

  const change = useCallback((fn: (s: StudioState) => StudioState, key?: string) => {
    const now = Date.now();
    const c = coalesce.current;
    const merge = !!key && !!c && c.key === key && now - c.at < COALESCE_MS;
    coalesce.current = key ? { key, at: now } : null;
    setModel((m) => {
      if (!m) return m;
      const next = fn(m.cur);
      if (sameState(next, m.cur)) return m;
      return merge
        ? { ...m, cur: next, future: [] }
        : { ...m, cur: next, past: [...m.past, m.cur].slice(-HISTORY), future: [] };
    });
  }, []);

  const undo = useCallback(() => {
    coalesce.current = null;
    setModel((m) => (m && m.past.length
      ? { ...m, cur: m.past[m.past.length - 1], past: m.past.slice(0, -1), future: [m.cur, ...m.future] }
      : m));
  }, []);

  const redo = useCallback(() => {
    coalesce.current = null;
    setModel((m) => (m && m.future.length
      ? { ...m, cur: m.future[0], future: m.future.slice(1), past: [...m.past, m.cur].slice(-HISTORY) }
      : m));
  }, []);

  const dirty = useMemo(() => !!model && !sameState(model.cur, model.saved), [model]);

  /** Guarda ya lo pendiente. Devuelve false si no se pudo. */
  const save = useCallback(async (): Promise<boolean> => {
    while (inflight.current) await inflight.current;
    const m = modelRef.current;
    if (!m || statusRef.current === "conflict") return statusRef.current !== "conflict";
    if (sameState(m.cur, m.saved)) return true;
    const sent = m.cur;
    setStatus("saving");
    const run = (async () => {
      try {
        const fresh = await api<ClipDetail>(`/api/clips/${clipId}`, {
          method: "PATCH", json: buildPatch(m.saved, sent, m.revision),
        });
        setModel((mm) => (mm ? { ...mm, saved: sent, revision: fresh.clip.editRevision } : mm));
        modelRef.current = modelRef.current && { ...modelRef.current, saved: sent, revision: fresh.clip.editRevision };
        qc.setQueryData(["clip", clipId], fresh);
        setStatus("saved");
        setError(null);
        return true;
      } catch (e) {
        const conflict = e instanceof ApiError && e.status === 409;
        failed.current = sent;
        setStatus(conflict ? "conflict" : "error");
        statusRef.current = conflict ? "conflict" : "error";
        setError((e as Error).message);
        return false;
      }
    })();
    inflight.current = run;
    try {
      return await run;
    } finally {
      inflight.current = null;
    }
  }, [clipId, qc]);

  // Autoguardado (tras un error, solo cuando vuelves a cambiar algo).
  const cur = model?.cur;
  useEffect(() => {
    if (!dirty || status === "conflict" || cur === failed.current) return;
    const t = setTimeout(() => void save(), AUTOSAVE_MS);
    return () => clearTimeout(t);
  }, [cur, dirty, status, save]);

  // Aviso al cerrar la pestaña con cambios sin guardar.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /** Descarta lo local y vuelve a cargar lo que hay en el servidor. */
  const reload = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: ["clip", clipId] });
    setLoadedFor(null);
  }, [clipId, qc]);

  return {
    state: model?.cur ?? null,
    revision: model?.revision ?? 0,
    canUndo: !!model?.past.length,
    canRedo: !!model?.future.length,
    dirty,
    status: dirty && status === "saved" ? "pending" : status,
    error,
    change,
    undo,
    redo,
    save,
    reload,
  };
}

export type Studio = ReturnType<typeof useStudio>;
