"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Check, CircleSlash, History, Loader2, Pause, Play, Redo2, RefreshCw, Repeat,
  SkipBack, SkipForward, Undo2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useClip, useHealth, useTemplates } from "@/lib/client";
import { applyGlossary, type GlossaryRule } from "@/lib/glossary";
import {
  DEFAULT_AUDIO, DEFAULT_EFFECTS, DEFAULT_FRAMING, MIN_SEGMENT, newSegmentId, PRESETS, type Preset, type Segment,
  segmentAt, totalDuration,
} from "@/lib/edit-doc";
import { timecode } from "@/lib/format";
import {
  firstEmoji, HOOK_EMOJIS, HOOK_MAX_CHARS, HOOK_MAX_WORDS, HOOK_TYPE_LABEL, hasEmoji, hookDisplaySeconds, hookPlain, sanitizeHook,
  spokenHookSeconds, withEmoji,
} from "@/lib/hook";
import type { ClipDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Choice, Knob } from "./editor/choice";
import { CoverPanel } from "./editor/cover-panel";
import { HashtagSuggestions } from "./editor/hashtag-suggestions";
import { PausingVideo } from "./pausing-video";
import { EffectsPanel } from "./editor/effects-panel";
import { FontPicker } from "./editor/font-picker";
import { FramingPanel } from "./editor/framing-panel";
import { Kbd } from "./editor/kbd";
import { createPlayhead, type Playhead, usePlayhead } from "./editor/playhead";
import { PublishKit } from "./editor/publish-kit";
import { SegmentsPanel } from "./editor/segments-panel";
import { type PreviewHandle, StudioPreview } from "./editor/studio-preview";
import { TemplatePicker } from "./editor/template-picker";
import { Timeline } from "./editor/timeline";
import { stateFromOriginal, type StudioState, useStudio, wordKey } from "./editor/use-studio";
import { WhyPanel } from "./editor/why-panel";
import { GlossaryPanel } from "./editor/glossary-panel";
import { WordsPanel } from "./editor/words-panel";

const FRAME = 1 / 30;
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
const MOD = isMac ? "⌘" : "Ctrl";

function SaveBadge({ status, error }: { status: string; error: string | null }) {
  if (status === "saving") {
    return <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" /> Guardando…</span>;
  }
  if (status === "pending") return <span className="text-xs text-muted-foreground">Cambios sin guardar</span>;
  if (status === "error") {
    return <span className="flex items-center gap-1.5 text-xs text-destructive" title={error ?? ""}><AlertTriangle className="size-3" /> No se guardó</span>;
  }
  if (status === "conflict") return null;
  return <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Check className="size-3 text-success" /> Guardado</span>;
}

function Tip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="text-xs">{label}</TooltipContent>
    </Tooltip>
  );
}

/** Tiempo del clip editado para un segundo del video fuente. */
function editTime(segments: Segment[], t: number): number | null {
  const i = segmentAt(segments, t);
  if (i < 0) return null;
  return totalDuration(segments.slice(0, i)) + (t - segments[i].start);
}

/** Contador «0:12.3 / 1:05.0»: se redibuja con la reproducción sin arrastrar al estudio. */
function TimeReadout({ playhead, segments, total }: { playhead: Playhead; segments: Segment[]; total: number }) {
  const et = editTime(segments, usePlayhead(playhead));
  return (
    <span className="tabular text-xs text-muted-foreground">
      {et == null ? "fuera del clip" : timecode(et, true)} / {timecode(total, true)}
    </span>
  );
}

export function ClipEditor({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useClip(id);
  const { data: templates } = useTemplates();
  const { data: health } = useHealth();
  const studio = useStudio(id, data);
  const { state, change, undo, redo, save } = studio;
  const preview = useRef<PreviewHandle>(null);
  // Tiempo de reproducción fuera del estado del estudio (ver playhead.ts).
  const [playhead] = useState(() => createPlayhead());
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<"edit" | "final">("edit");
  const [tab, setTab] = useState("tramos");
  const [sending, setSending] = useState(false);

  const segments = useMemo(() => state?.segments ?? [], [state?.segments]);
  const selected = segments.some((s) => s.id === picked) ? picked : segments[0]?.id ?? null;
  const original = useMemo(
    () => new Map((data?.original.words ?? []).map((w) => [wordKey(w.t), w.w])),
    [data?.original.words],
  );

  const set = useCallback(<K extends keyof StudioState>(k: K, v: StudioState[K], key?: string) => {
    change((s) => ({ ...s, [k]: v }), key);
  }, [change]);

  const setSegments = useCallback((next: Segment[], key?: string) => {
    if (next.length) change((s) => ({ ...s, segments: next }), key);
  }, [change]);

  // Callbacks estables: la línea de tiempo, las palabras y las plantillas no
  // se vuelven a pintar si lo suyo no cambió.
  const seek = useCallback((t: number) => preview.current?.seek(t), []);
  const moveSegment = useCallback((sid: string, start: number, end: number, key: string) => {
    change((s) => ({ ...s, segments: s.segments.map((x) => (x.id === sid ? { ...x, start, end } : x)) }), key);
  }, [change]);
  const setTemplate = useCallback((v: string) => set("templateId", v), [set]);
  const editWord = useCallback((k: string, patch: Partial<StudioState["words"][string]>) => {
    change((s) => ({ ...s, words: { ...s.words, [k]: { ...(s.words[k] ?? { w: "", hl: false }), ...patch } } }));
  }, [change]);
  const seekWord = useCallback((t: number) => {
    setView("edit");
    preview.current?.seek(t);
  }, []);

  /** Aplica reglas del glosario a las palabras del borrador (una sola acción de deshacer). */
  const words = data?.captions.words;
  const glossaryInDraft = useCallback((rules: GlossaryRule[]): number => {
    if (!words?.length) return 0;
    const pass = (overrides: StudioState["words"]) => {
      const seen = new Map<string, number>();
      words.forEach((w) => seen.set(wordKey(w.t), (seen.get(wordKey(w.t)) ?? 0) + 1));
      // Dos palabras con el mismo inicio comparten identidad en el borrador: no se tocan.
      const current = words.map((w) => ({ w: overrides[wordKey(w.t)]?.w ?? w.w }));
      const { texts, changed } = applyGlossary(current, rules, (i) => (seen.get(wordKey(words[i].t)) ?? 0) > 1);
      return { texts, changed };
    };
    const count = pass(state?.words ?? {}).changed.length;
    if (count) {
      change((s) => {
        const { texts, changed } = pass(s.words);
        const next = { ...s.words };
        for (const i of changed) {
          const k = wordKey(words[i].t);
          next[k] = { w: texts[i], hl: next[k]?.hl ?? words[i].hl };
        }
        return { ...s, words: next };
      });
    }
    return count;
  }, [change, state?.words, words]);

  const replaceAll = useCallback(async (rule: GlossaryRule, remember: boolean) => {
    if (!remember) {
      const n = glossaryInDraft([rule]);
      toast.success(n ? `${n} palabra(s) corregidas en este clip` : "No hay más coincidencias en este clip");
      return;
    }
    try {
      const r = await api<{ applied: { clips: number; words: number } }>("/api/glossary", {
        method: "POST", json: { ...rule, exceptClipId: id },
      });
      const n = glossaryInDraft([rule]);
      void qc.invalidateQueries({ queryKey: ["glossary"] });
      toast.success(`Regla guardada: «${rule.from}» → «${rule.to}»`, {
        description: `${n} palabra(s) en este clip (deshacer con ${MOD}+Z), ${r.applied.words} en ${r.applied.clips} clip(s) más. `
          + "Los clips nuevos la aplican solos; los ya renderizados necesitan renderizar de nuevo.",
        duration: 9000,
      });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [glossaryInDraft, id, qc]);

  /** Completa el texto con lo que Whisper se saltó: guarda el borrador, lo añade en el servidor y recarga. */
  const fillMissing = useCallback(async () => {
    try {
      if (!(await save())) return void toast.error("No se pudo guardar el borrador antes de completar el texto.");
      const r = await api<{ added: number }>(`/api/clips/${id}/captions`, { method: "POST" });
      await studio.reload();
      toast.success(r.added ? `${r.added} palabra(s) añadidas al texto` : "No faltaba texto",
        r.added ? { description: "Renderiza de nuevo para verlas en el video." } : undefined);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [id, save, studio]);

  const removeRule = useCallback(async (from: string) => {
    try {
      await api(`/api/glossary?from=${encodeURIComponent(from)}`, { method: "DELETE" });
      void qc.invalidateQueries({ queryKey: ["glossary"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [qc]);

  const locked = !!data?.project.sourceDeleted;
  const videoDuration = data?.project.durationSec ?? 0;

  const split = useCallback(() => {
    if (locked) return;
    const t = preview.current?.time() ?? playhead.get();
    const i = segmentAt(segments, t);
    if (i < 0) return void toast.info("Pon el cursor dentro de un tramo para dividirlo.");
    const s = segments[i];
    if (t - s.start < MIN_SEGMENT || s.end - t < MIN_SEGMENT) return void toast.info("Demasiado cerca del borde del tramo.");
    const right = { id: newSegmentId(), start: Math.round(t * 1000) / 1000, end: s.end };
    setSegments([...segments.slice(0, i), { ...s, end: right.start }, right, ...segments.slice(i + 1)]);
    setPicked(right.id);
  }, [locked, playhead, segments, setSegments]);

  const mark = useCallback((side: "start" | "end") => {
    if (locked || !selected) return;
    const t = Math.round((preview.current?.time() ?? playhead.get()) * 1000) / 1000;
    const s = segments.find((x) => x.id === selected);
    if (!s) return;
    if (side === "start" ? t > s.end - MIN_SEGMENT : t < s.start + MIN_SEGMENT) {
      return void toast.info(side === "start" ? "La entrada debe quedar antes de la salida." : "La salida debe quedar después de la entrada.");
    }
    setSegments(segments.map((x) => (x.id === selected ? { ...x, [side]: t } : x)));
  }, [locked, playhead, segments, selected, setSegments]);

  const duplicate = useCallback((sid: string) => {
    const i = segments.findIndex((s) => s.id === sid);
    if (i < 0 || segments.length >= 20) return;
    const copy = { ...segments[i], id: newSegmentId() };
    setSegments([...segments.slice(0, i + 1), copy, ...segments.slice(i + 1)]);
    setPicked(copy.id);
  }, [segments, setSegments]);

  // Atajos (inactivos mientras escribes o con un diálogo abierto).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], [role=dialog], [role=listbox], [role=menu]")) return;
      const mod = e.metaKey || e.ctrlKey;
      const k = e.key.toLowerCase();
      if (mod && k === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if (mod && k === "y") {
        e.preventDefault();
        redo();
        return;
      }
      if (mod && k === "s") {
        e.preventDefault();
        void save();
        return;
      }
      if (mod || e.altKey) return;
      const control = target?.closest("button, [role=slider], [role=radio], [role=switch], [role=tab]");
      if (e.key === " " && !control) {
        e.preventDefault();
        preview.current?.toggle();
      } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !control) {
        e.preventDefault();
        preview.current?.step((e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 1 : FRAME));
      } else if (k === "i") mark("start");
      else if (k === "o") mark("end");
      else if (k === "s") split();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mark, redo, save, split, undo]);

  if (isLoading || !state) {
    if (error) return <p className="pt-10 text-destructive">{(error as Error).message}</p>;
    return (
      <div className="grid gap-6 pt-8 lg:grid-cols-[340px_1fr]">
        <Skeleton className="aspect-[9/16]" />
        <Skeleton className="h-[480px]" />
      </div>
    );
  }
  if (error || !data) return <p className="pt-10 text-destructive">{(error as Error)?.message ?? "Clip no encontrado"}</p>;

  const { clip, project, captions } = data as ClipDetail;
  const busy = clip.renderStatus === "QUEUED" || clip.renderStatus === "RUNNING";
  const stale = clip.renderStatus !== "DONE" || clip.editRevision !== clip.renderedRevision || studio.dirty;
  const limits = {
    min: health?.clipMinSec ?? 60, max: health?.clipMaxSec ?? 150, ideal: clip.signals.arc?.duration ?? null,
  };
  const template = templates?.find((t) => t.id === state.templateId);
  const autoHookSeconds = hookDisplaySeconds(state.hook, template?.hookDuration,
    spokenHookSeconds(clip.signals.arc?.hook_seconds, clip.startSec, segments));
  const total = totalDuration(segments);
  const hookClean = sanitizeHook(state.hook);
  // Versiones del gancho que propuso la IA (la original del análisis incluida,
  // para poder volver a ella), sin la que ya está puesta.
  const hookOptions = [data.original.hook, clip.hook, ...(clip.signals.arc?.hook_options ?? [])]
    .filter((h, i, all) => h && sanitizeHook(h) !== hookClean && all.indexOf(h) === i);
  const hookWords = hookPlain(state.hook).split(" ").filter(Boolean).length;

  async function render() {
    setSending(true);
    try {
      if (!(await save())) {
        toast.error("No se pudo guardar el borrador; revisa el aviso de arriba.");
        return;
      }
      await api(`/api/clips/${id}/render`, { method: "POST" });
      toast.success("Renderizando el clip");
      await qc.invalidateQueries({ queryKey: ["clip", id] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  async function cancelRender() {
    try {
      await api(`/api/clips/${id}/cancel`, { method: "POST" });
      toast.success("Render cancelado; el video anterior se conserva");
      await qc.invalidateQueries({ queryKey: ["clip", id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function sendJob(path: string, body: unknown, ok: string) {
    try {
      if (!(await save())) return;
      await api(path, { method: "POST", json: body });
      toast.success(ok);
      await qc.invalidateQueries({ queryKey: ["clip", id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  function restoreOriginal() {
    change((s) => stateFromOriginal(data!.original, s, {
      framing: DEFAULT_FRAMING, effects: DEFAULT_EFFECTS, audio: DEFAULT_AUDIO, preset: "tiktok", font: null,
      punch: true, hookSeconds: null,
    }));
    toast.success(`Original restaurado. Deshaz con ${MOD}+Z si te arrepientes.`);
  }

  const finalRatio = clip.aspect === "square" ? "1 / 1" : clip.aspect === "original" ? "16 / 9" : "9 / 16";

  return (
    <div className="pt-5">
      {/* Cabecera */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/projects/${project.id}`} className="inline-flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4 shrink-0" />
          <span className="truncate">{project.title}</span>
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <SaveBadge status={studio.status} error={studio.error} />
          <Tip label={`Deshacer (${MOD}+Z)`}>
            <Button variant="ghost" size="icon-sm" aria-label="Deshacer" disabled={!studio.canUndo} onClick={undo}><Undo2 /></Button>
          </Tip>
          <Tip label={`Rehacer (${MOD}+Shift+Z)`}>
            <Button variant="ghost" size="icon-sm" aria-label="Rehacer" disabled={!studio.canRedo} onClick={redo}><Redo2 /></Button>
          </Tip>
          <Tip label="Vuelve al clip tal como lo eligió el análisis (se puede deshacer)">
            <Button variant="ghost" size="sm" onClick={restoreOriginal}><History /> Restaurar original</Button>
          </Tip>
          {busy ? (
            <div className="flex items-center gap-2">
              <div className="w-36">
                <Progress value={clip.renderStatus === "RUNNING" ? clip.renderProgress : 0} aria-label="Avance del render" />
                <p className="tabular mt-1 text-[11px] text-muted-foreground">
                  {clip.renderStatus === "RUNNING" ? `Renderizando ${clip.renderProgress} %` : "En cola"}
                </p>
              </div>
              <Button variant="secondary" size="sm" onClick={cancelRender}><CircleSlash /> Cancelar</Button>
            </div>
          ) : (
            <Button onClick={render} disabled={sending || studio.status === "conflict"}>
              {sending ? <Loader2 className="animate-spin" /> : null}
              {stale ? "Renderizar" : "Renderizar de nuevo"}
            </Button>
          )}
        </div>
      </div>

      {studio.status === "conflict" && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <span>{studio.error}</span>
          <Button size="sm" variant="secondary" onClick={() => void studio.reload()}><RefreshCw /> Recargar el borrador</Button>
        </div>
      )}
      {studio.status === "error" && studio.error && (
        <p className="mt-3 flex items-center gap-2 text-sm text-destructive"><AlertTriangle className="size-4" /> {studio.error}</p>
      )}

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(260px,360px)_1fr]">
        {/* Visor */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <Tabs value={view} onValueChange={(v) => setView(v as "edit" | "final")} className="mb-3">
            <TabsList className="w-full">
              <TabsTrigger value="edit" className="flex-1">Edición</TabsTrigger>
              <TabsTrigger value="final" className="flex-1 gap-2" title={stale && clip.renderStatus === "DONE" ? "Desactualizado: hay cambios sin renderizar" : undefined}>
                Render final
                {stale && clip.renderStatus === "DONE" && (
                  <>
                    <span aria-hidden className="size-1.5 rounded-full bg-primary" />
                    <span className="sr-only">(desactualizado)</span>
                  </>
                )}
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <div className={cn(view !== "edit" && "hidden")}>
            <StudioPreview
              ref={preview}
              active={view === "edit"}
              sourceUrl={project.sourceVideoUrl}
              segments={segments}
              framing={state.framing}
              effects={state.effects}
              audio={state.audio}
              loop={loop}
              onTime={playhead.set}
              onPlaying={setPlaying}
              onMove={(x, y) => change((s) => ({ ...s, framing: { ...s.framing, x, y } }), "drag-framing")}
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="flex items-center gap-0.5">
                <Tip label="Cuadro anterior (←) · 1 s con Shift">
                  <Button variant="ghost" size="icon-sm" aria-label="Retroceder" onClick={() => preview.current?.step(-FRAME)}><SkipBack /></Button>
                </Tip>
                <Tip label="Reproducir o pausar (Espacio)">
                  <Button size="icon-sm" aria-label={playing ? "Pausar" : "Reproducir"} onClick={() => preview.current?.toggle()}>
                    {playing ? <Pause /> : <Play />}
                  </Button>
                </Tip>
                <Tip label="Cuadro siguiente (→) · 1 s con Shift">
                  <Button variant="ghost" size="icon-sm" aria-label="Avanzar" onClick={() => preview.current?.step(FRAME)}><SkipForward /></Button>
                </Tip>
                <Toggle size="sm" variant="pink" pressed={loop} onPressedChange={setLoop} aria-label="Repetir en bucle" title="Repetir en bucle">
                  <Repeat />
                </Toggle>
              </div>
              <TimeReadout playhead={playhead} segments={segments} total={total} />
            </div>
          </div>
          {view === "final" && (
            clip.videoUrl ? (
              <PausingVideo key={clip.videoUrl} src={clip.videoUrl} poster={clip.thumbUrl ?? undefined} controls loop playsInline
                className="w-full rounded-xl bg-black object-contain" style={{ aspectRatio: finalRatio }} />
            ) : (
              <div className="grid aspect-[9/16] place-items-center rounded-xl bg-well p-6 text-center text-sm text-muted-foreground">
                Aún no hay render. Pulsa «Renderizar» para verlo.
              </div>
            )
          )}
          {clip.renderStatus === "FAILED" && (
            <p className="mt-3 flex gap-2 text-xs text-destructive"><AlertTriangle className="size-4 shrink-0" /> {clip.renderError}</p>
          )}
          {clip.qaWarnings.length > 0 && clip.renderStatus === "DONE" && (
            <ul className="mt-3 space-y-1 text-xs text-primary">
              {clip.qaWarnings.map((w) => (
                <li key={w} className="flex gap-2"><AlertTriangle className="size-3.5 shrink-0" /> {w}</li>
              ))}
            </ul>
          )}
        </div>

        {/* Línea de tiempo e inspector */}
        <div className="min-w-0">
          <Timeline
            clipId={id}
            videoDuration={videoDuration}
            segments={segments}
            selectedId={selected}
            playhead={playhead}
            disabled={locked}
            onSeek={seek}
            onSelect={setPicked}
            onChange={moveSegment}
          />
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            <Kbd className="ml-0">Espacio</Kbd> reproducir · <Kbd>←</Kbd><Kbd>→</Kbd> cuadro (Shift: 1 s) · <Kbd>I</Kbd>/<Kbd>O</Kbd> entrada y
            salida · <Kbd>S</Kbd> dividir · <Kbd>{MOD}</Kbd>+<Kbd>Z</Kbd> deshacer · <Kbd>{MOD}</Kbd>+<Kbd>S</Kbd> guardar
          </p>

          <Tabs value={tab} onValueChange={setTab} variant="underline" className="mt-5">
            <TabsList className="flex w-full flex-wrap justify-start">
              <TabsTrigger value="tramos">Tramos</TabsTrigger>
              <TabsTrigger value="texto">Texto</TabsTrigger>
              <TabsTrigger value="encuadre">Encuadre</TabsTrigger>
              <TabsTrigger value="efectos">Efectos</TabsTrigger>
              <TabsTrigger value="publicar">Publicar</TabsTrigger>
              <TabsTrigger value="porque">Por qué</TabsTrigger>
            </TabsList>

            <TabsContent value="tramos" className="pt-4">
              {locked && <p className="mb-3 text-xs text-muted-foreground">El video fuente se borró con «Limpiar»: los tramos quedan fijos.</p>}
              <SegmentsPanel
                clip={clip}
                segments={segments}
                selectedId={selected}
                videoDuration={videoDuration}
                disabled={locked}
                limits={limits}
                onSelect={setPicked}
                onChange={setSegments}
                onSplit={split}
                onDuplicate={duplicate}
                onMarkIn={() => mark("start")}
                onMarkOut={() => mark("end")}
                onSeek={(t) => preview.current?.seek(t)}
              />
            </TabsContent>

            <TabsContent value="texto" className="space-y-6 pt-4">
              <section>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <Label htmlFor="hook" className="text-sm font-semibold">Gancho: título, descripción y portada</Label>
                  <span className={cn("tabular text-xs", hookWords > HOOK_MAX_WORDS ? "text-destructive" : "text-muted-foreground")}>
                    {hookWords}/{HOOK_MAX_WORDS} palabras · {hookClean.length}/{HOOK_MAX_CHARS}
                  </span>
                </div>
                <Input id="hook" value={state.hook} maxLength={120} onChange={(e) => set("hook", e.target.value, "hook")} />
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <span className="mr-1 text-xs text-muted-foreground">Emoji al final:</span>
                  {HOOK_EMOJIS.map((e) => (
                    <button
                      key={e}
                      type="button"
                      aria-label={`Terminar con ${e}`}
                      onClick={() => set("hook", withEmoji(state.hook, e))}
                      className={cn("rounded-md border px-1.5 py-0.5 text-base leading-none outline-none hover:border-primary focus-visible:ring-2 focus-visible:ring-ring",
                        firstEmoji(state.hook) === e ? "border-primary bg-primary/10" : "border-border")}
                    >
                      {e}
                    </button>
                  ))}
                </div>
                {hookOptions.length > 0 && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-muted-foreground">Otras opciones:</span>
                    {hookOptions.map((h) => (
                      <button
                        key={h}
                        type="button"
                        onClick={() => set("hook", h)}
                        className="rounded-md border border-border px-2 py-0.5 text-xs outline-none hover:border-primary hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {h}
                      </button>
                    ))}
                  </div>
                )}
                <p className="mt-1.5 text-xs text-muted-foreground">
                  Un solo texto para todo: es el título y la descripción del post, la portada y el nombre de los archivos.
                  En el video va arriba al empezar, en una línea o en dos equilibradas, con el emoji a color encima de la caja;
                  los números y las palabras fuertes van en el color de acento.
                  {hookClean !== state.hook.trim() && hookClean ? <> Se usará como: «{hookClean}».</> : null}
                  {hookClean && !hasEmoji(hookClean) ? <> Le falta un emoji al final (mira las opciones de arriba).</> : null}
                  {clip.hookType ? <> Tipo de gancho: <span className="text-foreground">{HOOK_TYPE_LABEL[clip.hookType] ?? clip.hookType}</span>.</> : null}
                </p>
                <div className="mt-3 space-y-2">
                  <div className="flex items-start gap-3">
                    <Switch
                      id="hook-auto"
                      checked={state.hookSeconds == null}
                      onCheckedChange={(auto) => set("hookSeconds", auto ? null : autoHookSeconds)}
                    />
                    <Label htmlFor="hook-auto" className="block text-sm leading-snug font-normal">
                      Tiempo en pantalla automático{state.hookSeconds == null ? `: ${autoHookSeconds.toFixed(1).replace(".", ",")} s` : ""}
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        Lo que se tarda en leerlo, sin bajar del mínimo de la plantilla y acompañando al gancho hablado
                        (máx. 6 s).
                      </span>
                    </Label>
                  </div>
                  {state.hookSeconds != null && (
                    <Knob label="En pantalla" value={state.hookSeconds} min={1.5} max={8} step={0.1}
                      format={(v) => `${v.toFixed(1).replace(".", ",")} s`}
                      onChange={(v) => set("hookSeconds", Math.round(v * 10) / 10, "hook-seconds")} />
                  )}
                </div>
              </section>

              <section>
                <h3 className="mb-2 text-sm font-semibold">Plantilla de subtítulos</h3>
                {templates ? (
                  <TemplatePicker templates={templates} value={state.templateId} font={state.font}
                    projectTemplate={project.templateId} onChange={setTemplate} />
                ) : <Skeleton className="h-24" />}
                <p className="mt-2 text-xs text-muted-foreground">
                  Estilo OpusClip: palabras fuertes, números y las que destaques en color de énfasis
                  {health?.emoji === false ? "." : "; las plantillas con emojis añaden un emoji a color sobre algunas palabras clave."}
                </p>
              </section>

              <section>
                <h3 className="mb-2 text-sm font-semibold">Fuente</h3>
                <FontPicker value={state.font} onChange={(f) => set("font", f)} />
              </section>

              <section>
                <div className="flex items-start gap-3">
                  <Switch id="smartcut" checked={state.smartCut} onCheckedChange={(v) => set("smartCut", v)} />
                  <Label htmlFor="smartcut" className="block text-sm leading-snug font-normal">
                    Corte inteligente
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      Quita silencios largos y muletillas (acorta el clip). Puede comerse una pausa dramática.
                    </span>
                  </Label>
                </div>
              </section>

              <section>
                <h3 className="mb-2 text-sm font-semibold">Palabras</h3>
                <WordsPanel
                  words={captions.words}
                  overrides={state.words}
                  original={original}
                  segments={segments}
                  source={captions.source}
                  onEdit={editWord}
                  onSeek={seekWord}
                  onReplaceAll={replaceAll}
                  missing={captions.missing}
                  onFillMissing={fillMissing}
                />
                <GlossaryPanel onAdd={(from, to) => replaceAll({ from, to }, true)} onRemove={removeRule} />
              </section>
            </TabsContent>

            <TabsContent value="encuadre" className="pt-4">
              <FramingPanel
                framing={state.framing}
                layoutMode={state.layoutMode}
                onFraming={(patch, key) => change((s) => ({ ...s, framing: { ...s.framing, ...patch } }), key)}
                onLayout={(mode) => set("layoutMode", mode)}
              />
            </TabsContent>

            <TabsContent value="efectos" className="pt-4">
              <EffectsPanel
                effects={state.effects}
                audio={state.audio}
                punch={state.punch}
                onPunch={(v) => set("punch", v)}
                autoFraming={state.framing.mode === "auto" && state.framing.aspect !== "original"}
                onEffects={(patch, key) => change((s) => ({ ...s, effects: { ...s.effects, ...patch } }), key)}
                onAudio={(patch, key) => change((s) => ({ ...s, audio: { ...s.audio, ...patch } }), key)}
              />
            </TabsContent>

            <TabsContent value="publicar" className="space-y-6 pt-4">
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">Exportación</h3>
                <Choice<Preset>
                  label="Preajuste de exportación"
                  value={state.preset}
                  onChange={(v) => set("preset", v)}
                  options={PRESETS.map((p) => ({ value: p.id, label: p.label, hint: `Tope de ${p.maxrate}` }))}
                />
                <p className="text-xs text-muted-foreground">
                  H.264 + AAC con tope de {PRESETS.find((p) => p.id === state.preset)?.maxrate}. El formato
                  ({clip.aspect === "square" ? "1:1" : clip.aspect === "original" ? "original" : "9:16"}) se elige en Encuadre.
                </p>
              </section>
              <PublishKit
                clip={clip}
                hook={state.hook}
                hashtags={state.hashtags}
                onChange={(k, v) => set(k, v, `kit-${k}`)}
                health={health}
                onPosted={async (posted) => {
                  try {
                    qc.setQueryData(["clip", id], await api<ClipDetail>(`/api/clips/${id}`, { method: "PATCH", json: { posted } }));
                  } catch (e) {
                    toast.error((e as Error).message);
                  }
                }}
                onUploadPost={() => sendJob(`/api/clips/${id}/publish`, { platforms: ["youtube"] }, "Publicación en cola")}
              />
              <CoverPanel
                key={`${clip.coverUrl}|${JSON.stringify(clip.cover)}`}
                clip={clip}
                hook={state.hook}
                pickTime={() => {
                  const t = preview.current?.time() ?? playhead.get();
                  return editTime(segments, t) == null ? null : t;
                }}
                toClipTime={(t) => editTime(segments, t)}
                onUpdated={() => void qc.invalidateQueries({ queryKey: ["clip", id] })}
              />
              <HashtagSuggestions clipId={id} sets={clip.hashtagSets} health={health}
                onUse={(tags) => set("hashtags", tags)} />
            </TabsContent>

            <TabsContent value="porque" className="pt-4">
              <WhyPanel clip={clip} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
