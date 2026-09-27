"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Clock, FileText, Languages, Pause, Play, RotateCcw, Sparkles, Square, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, useProject } from "@/lib/client";
import { ACTIVE_STATUSES, duration, llmLabel, TRANSCRIPT_LABEL } from "@/lib/format";
import type { ProjectDTO } from "@/lib/types";
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

export function ProjectView({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useProject(id);
  const [renderingAll, setRenderingAll] = useState(false);

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

  const { project, clips } = data;
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
                {clips.length} clips, del mejor al peor
              </h2>
              <p className="text-sm text-muted-foreground">
                El puntaje combina el juicio de la IA con el heatmap de YouTube, la energía del audio y el gancho.
              </p>
            </div>
            {pending > 0 && (
              <Button size="sm" onClick={renderAll} disabled={renderingAll}>
                Renderizar {pending === clips.length ? "todos" : `los ${pending} pendientes`}
              </Button>
            )}
          </div>
          <div className="mt-6 grid grid-cols-2 gap-x-5 gap-y-8 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {clips.map((c) => (
              <ClipCard key={c.id} clip={c} onRender={render} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
