"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Captions, Clock, Coins, Combine, FileText, FolderDown, Languages, Loader2, Pause, Play, RotateCcw, Scissors,
  Sparkles, Square, Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, useProject, useTemplates } from "@/lib/client";
import { canPickFolder, downloadOneByOne, exportPlan, exportToFolder } from "@/lib/export-folder";
import { ACTIVE_STATUSES, aiUsage, duration, llmLabel, TRANSCRIPT_LABEL } from "@/lib/format";
import { formatClock } from "@/lib/sources";
import type { ClipDTO, ProjectDTO } from "@/lib/types";
import { cssFont } from "./editor/template-picker";
import { ClipCard } from "./clip-card";
import { PhaseBar, StatusBadge } from "./status";

function Meta({ icon: Icon, children }: { icon: typeof Clock; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="size-3.5" /> {children}
    </span>
  );
}

function Controls({ project, onAction }: { project: ProjectDTO; onAction: (a: string) => Promise<void> }) {
  const router = useRouter();
  const active = ACTIVE_STATUSES.includes(project.status) && project.status !== "UPLOADING";
  async function discard() {
    try {
      await api(`/api/projects/${project.id}`, { method: "DELETE" });
      toast.success("Proyecto descartado");
      router.push("/");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <div className="flex flex-wrap gap-2">
      {active && (
        <Button variant="secondary" size="sm" onClick={() => onAction("pause")}>
          <Pause /> Pausar
        </Button>
      )}
      {project.status === "PAUSED" && (
        <Button size="sm" onClick={() => onAction("resume")}>
          <Play /> Reanudar
        </Button>
      )}
      {(active || project.status === "PAUSED") && (
        <Button variant="secondary" size="sm" onClick={() => onAction("stop")}>
          <Square /> Detener y conservar lo hecho
        </Button>
      )}
      {(project.status === "FAILED" || project.status === "STOPPED") && (
        <Button size="sm" onClick={() => onAction("retry")}>
          <RotateCcw /> Reintentar
        </Button>
      )}
      {project.status === "READY" && !project.sourceDeleted && (
        <Button variant="secondary" size="sm" onClick={() => onAction("reanalyze")}>
          <Sparkles /> Volver a buscar momentos
        </Button>
      )}
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="destructive" size="sm">
            <Trash2 /> Descartar
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Descartar este proyecto?</AlertDialogTitle>
            <AlertDialogDescription>
              Se borran el video, la transcripción y todos sus clips del disco. No se puede deshacer.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={discard}>Descartar proyecto</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

type ClipSort = "recent" | "score";
const SORT_KEY = "clipai.clipSort";

function readSort(): ClipSort {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(SORT_KEY) === "score" ? "score" : "recent";
  } catch {
    return "recent";
  }
}

/** Orden de la cuadrícula: el de publicación (más recientes primero) o el puntaje. */
function sortClips(clips: ClipDTO[], sort: ClipSort): ClipDTO[] {
  if (sort === "score") return clips; // la API los da del mejor al peor
  return [...clips].sort((a, b) => (a.order ?? Infinity) - (b.order ?? Infinity));
}

/** Estilo de subtítulos de todo el proyecto (luego cada clip se cambia en el estudio). */
function ProjectTemplate({ project, clips, onRender }: {
  project: ProjectDTO; clips: ClipDTO[]; onRender: (clipId: string) => Promise<void>;
}) {
  const qc = useQueryClient();
  const { data: templates } = useTemplates();
  const [busy, setBusy] = useState(false);
  const counts = new Map<string, number>();
  for (const c of clips) counts.set(c.templateId, (counts.get(c.templateId) ?? 0) + 1);
  const current = project.templateId ?? [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  const mixed = counts.size > 1;

  async function apply(templateId: string) {
    setBusy(true);
    try {
      const r = await api<{ changed: number }>(`/api/projects/${project.id}`, { method: "PATCH", json: { templateId } });
      await qc.invalidateQueries({ queryKey: ["project", project.id] });
      const name = templates?.find((t) => t.id === templateId)?.name ?? templateId;
      const rendered = clips.filter((c) => c.templateId !== templateId && c.renderStatus === "DONE");
      toast.success(`Subtítulos «${name}» en ${r.changed ? `${r.changed} clip(s)` : "todos los clips"}`, rendered.length ? {
        description: `${rendered.length} clip(s) ya renderizados tienen el estilo anterior hasta que los renderices.`,
        action: { label: "Renderizar ahora", onClick: () => void Promise.all(rendered.map((c) => onRender(c.id))) },
        duration: 10_000,
      } : undefined);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!templates?.length) return null;
  return (
    <Select value={current} onValueChange={(v) => void apply(v)} disabled={busy}>
      <SelectTrigger size="sm" className="max-w-60" aria-label="Estilo de subtítulos del proyecto"
        title="Se aplica a todos los clips del proyecto; en el estudio puedes cambiar el de cada uno.">
        {busy ? <Loader2 className="animate-spin" /> : <Captions />}
        <SelectValue placeholder="Subtítulos">
          {templates.find((t) => t.id === current)?.name ?? "Subtítulos"}{mixed ? " (mixto)" : ""}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {templates.map((t) => (
          <SelectItem key={t.id} value={t.id}>
            <span style={{ ...cssFont(t.font), color: t.highlight }}>{t.name}</span>
            {counts.get(t.id) ? <span className="ml-1 text-xs text-muted-foreground">({counts.get(t.id)})</span> : null}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Todos los videos con su portada, en orden de publicación, a una carpeta que eliges. */
function DownloadAll({ project, clips }: { project: ProjectDTO; clips: ClipDTO[] }) {
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const plan = exportPlan(clips);

  async function run() {
    const { items, pending, outdated } = plan;
    const notes = [
      pending.length ? `${pending.length} sin renderizar no se incluyen.` : "",
      outdated.length ? `${outdated.length} con cambios sin renderizar van con su último render.` : "",
    ].filter(Boolean).join(" ");
    try {
      if (!canPickFolder()) {
        toast.info("Este navegador no deja elegir carpeta: se descargan a Descargas con los mismos nombres (usa Chrome o Edge para elegirla).");
        await downloadOneByOne(items, (done, total) => setProgress({ done, total }));
        toast.success(`${items.length} video(s) con su portada descargados`, notes ? { description: notes } : undefined);
        return;
      }
      const r = await exportToFolder(project, items, (done, total) => setProgress({ done, total }));
      if (r) {
        toast.success(`${items.length} video(s) con su portada en «${r.folder}»`, {
          description: `Numerados en orden de publicación (01 primero), con «00 - Orden de publicación.txt». ${notes}`.trim(),
          duration: 10_000,
        });
      }
    } catch (e) {
      toast.error(`No se pudo terminar la descarga: ${(e as Error).message}`);
    } finally {
      setProgress(null);
    }
  }

  const n = plan.items.length;
  return (
    <Button size="sm" variant="secondary" onClick={run} disabled={!n || !!progress}
      title={n ? "Elige una carpeta: se crea una subcarpeta con el proyecto, cada video con su portada al lado y numerados en orden de publicación."
        : "Renderiza algún clip primero"}>
      {progress ? <Loader2 className="animate-spin" /> : <FolderDown />}
      {progress ? `Guardando ${progress.done}/${progress.total}` : `Descargar todo${n ? ` (${n})` : ""}`}
    </Button>
  );
}

export function ProjectView({ id }: { id: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const { data, isLoading, error } = useProject(id);
  const [renderingAll, setRenderingAll] = useState(false);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [combining, setCombining] = useState(false);
  const [sort, setSortState] = useState<ClipSort>(readSort);

  function setSort(v: ClipSort) {
    setSortState(v);
    try {
      window.localStorage.setItem(SORT_KEY, v);
    } catch {
      // modo privado: el orden no se recuerda
    }
  }

  function togglePick(clipId: string) {
    setPicked((p) => (p.includes(clipId) ? p.filter((x) => x !== clipId) : [...p, clipId].slice(0, 10)));
  }

  async function combine() {
    setCombining(true);
    try {
      const res = await api<{ id: string }>(`/api/projects/${id}/combine`, { method: "POST", json: { clipIds: picked } });
      toast.success("Clip combinado creado; renderizando");
      setPicking(false);
      setPicked([]);
      await qc.invalidateQueries({ queryKey: ["project", id] });
      router.push(`/clips/${res.id}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setCombining(false);
    }
  }

  async function action(a: string) {
    try {
      await api(`/api/projects/${id}/control`, { method: "POST", json: { action: a } });
      qc.invalidateQueries({ queryKey: ["project", id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function render(clipId: string) {
    try {
      await api(`/api/clips/${clipId}/render`, { method: "POST" });
      qc.invalidateQueries({ queryKey: ["project", id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function renderAll() {
    setRenderingAll(true);
    for (const c of data?.clips ?? []) {
      if (c.renderStatus === "NONE" || c.renderStatus === "FAILED") await render(c.id);
    }
    setRenderingAll(false);
  }

  if (isLoading) {
    return (
      <div className="pt-8">
        <Skeleton className="h-10 w-2/3" />
        <div className="mt-8 grid grid-cols-2 gap-5 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="aspect-[9/16]" />
          ))}
        </div>
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="pt-10">
        <p className="text-destructive">{(error as Error)?.message ?? "Proyecto no encontrado"}</p>
        <Link href="/" className="mt-4 inline-block text-sm underline">
          Volver a proyectos
        </Link>
      </div>
    );
  }

  const { project } = data;
  const clips = sortClips(data.clips, sort);
  const active = ACTIVE_STATUSES.includes(project.status);
  const pending = clips.filter((c) => c.renderStatus === "NONE" || c.renderStatus === "FAILED").length;

  return (
    <div className="pt-6">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Proyectos
      </Link>

      <header className="mt-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <StatusBadge status={project.status} />
            {project.query && <span className="truncate text-xs text-primary">Buscando: {project.query}</span>}
          </div>
          <h1 className="font-condensed mt-2 text-3xl leading-tight font-extrabold text-balance sm:text-4xl">
            {project.title || "Preparando el video"}
          </h1>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {project.durationSec ? <Meta icon={Clock}>{duration(project.durationSec)}</Meta> : null}
            {project.language ? <Meta icon={Languages}>{project.language}</Meta> : null}
            {project.transcriptSource ? (
              <Meta icon={FileText}>{TRANSCRIPT_LABEL[project.transcriptSource] ?? project.transcriptSource}</Meta>
            ) : null}
            {project.llmProvider ? <Meta icon={Sparkles}>{llmLabel(project.llmProvider)}</Meta> : null}
            {project.aiTokens > 0 ? (
              <span title="Estimado con los precios de lista de Google; incluye los tokens de razonamiento. Suma las llamadas de IA del análisis. Un análisis reutilizado de la caché no cuesta nada.">
                <Meta icon={Coins}>{aiUsage(project.aiCostUsd, project.aiTokens, project.aiCostEstimated, project.llmProvider)}</Meta>
              </span>
            ) : null}
            {project.rangeEndSec != null ? (
              <span title="Solo se descargó ese tramo del VOD: los tiempos de los clips cuentan desde su inicio.">
                <Meta icon={Scissors}>Tramo del VOD {formatClock(project.rangeStartSec ?? 0)} – {formatClock(project.rangeEndSec)}</Meta>
              </span>
            ) : null}
            {project.sourceUrl ? (
              <a href={project.sourceUrl} target="_blank" rel="noreferrer" className="underline-offset-4 hover:underline">
                Ver original
              </a>
            ) : null}
          </div>
        </div>
        <Controls project={project} onAction={action} />
      </header>

      {(active || project.status === "PAUSED") && (
        <section className="mt-8 rounded-xl border border-border bg-card p-5" aria-live="polite">
          <PhaseBar project={project} />
          <p className="mt-4 text-sm">
            <span className="tabular font-semibold text-primary">{project.progress}%</span>{" "}
            <span className="text-muted-foreground">{project.stage ?? "En cola"}</span>
          </p>
        </section>
      )}

      {project.status === "FAILED" && project.error && (
        <section className="mt-8 rounded-xl border border-destructive/40 bg-destructive/10 p-5 text-sm">
          <p className="font-semibold text-destructive">No se pudo terminar el proyecto</p>
          <p className="mt-1 whitespace-pre-wrap text-foreground/90">{project.error}</p>
        </section>
      )}

      {clips.length > 0 && (
        <section className="mt-10" aria-labelledby="clips-title">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="clips-title" className="font-condensed text-2xl font-bold">
                {clips.length} clips, {sort === "recent" ? "en orden de publicación" : "del mejor al peor"}
              </h2>
              <p className="text-sm text-muted-foreground">
                {sort === "recent"
                  ? "Del más reciente al más antiguo (los de un mismo análisis, del mejor al peor). El número de cada clip va en el nombre de su MP4 y de su portada."
                  : "El puntaje combina el juicio de la IA con el heatmap de YouTube, la energía del audio y el gancho."}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ToggleGroup type="single" variant="pink" size="sm" value={sort} aria-label="Orden de los clips"
                onValueChange={(v) => v && setSort(v as ClipSort)}>
                <ToggleGroupItem value="recent"
                  title="Más recientes primero: el orden en que conviene publicarlos">Recientes</ToggleGroupItem>
                <ToggleGroupItem value="score">
                  Puntaje
                </ToggleGroupItem>
              </ToggleGroup>
              <ProjectTemplate project={project} clips={clips} onRender={render} />
              {!picking && <DownloadAll project={project} clips={clips} />}
              {clips.length > 1 && !project.sourceDeleted && (picking ? (
                <>
                  <span className="text-xs text-muted-foreground">
                    {picked.length < 2 ? "Elige 2 o más, en el orden en que irán" : `${picked.length} elegidos`}
                  </span>
                  <Button size="sm" onClick={combine} disabled={picked.length < 2 || combining}>
                    {combining ? <Loader2 className="animate-spin" /> : <Combine />} Combinar
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => { setPicking(false); setPicked([]); }}>
                    Cancelar
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => setPicking(true)}>
                  <Combine /> Combinar clips
                </Button>
              ))}
              {pending > 0 && !picking && (
                <Button size="sm" onClick={renderAll} disabled={renderingAll}>
                  Renderizar {pending === clips.length ? "todos" : `los ${pending} pendientes`}
                </Button>
              )}
            </div>
          </div>
          <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {clips.map((c) => (
              <ClipCard
                key={c.id}
                clip={c}
                onRender={render}
                selection={picking ? { order: picked.includes(c.id) ? picked.indexOf(c.id) + 1 : null, onToggle: () => togglePick(c.id) } : undefined}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
