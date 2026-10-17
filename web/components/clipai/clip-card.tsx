"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Pencil, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/client";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { timecode } from "@/lib/format";
import { HOOK_TYPE_LABEL } from "@/lib/hook";
import type { ClipDTO } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PausingVideo } from "./pausing-video";
import { SaveClipMenu } from "./save-clip";

/** Eliminar un clip (con confirmación: borra su video, portada y borrador del disco). */
function DeleteClip({ clip }: { clip: ClipDTO }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const running = clip.renderStatus === "RUNNING" || clip.publishStatus === "RUNNING";

  async function remove() {
    setBusy(true);
    try {
      await api(`/api/clips/${clip.id}`, { method: "DELETE" });
      toast.success("Clip eliminado");
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["project", clip.projectId] }),
        qc.invalidateQueries({ queryKey: ["projects"] }),
      ]);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button size="icon-sm" variant="outline" aria-label="Eliminar clip" disabled={busy || running}
          title={running ? "Se está procesando: cancela el render o espera" : "Eliminar este clip"}
          className="hover:border-destructive/60 hover:text-destructive">
          {busy ? <Loader2 className="animate-spin" /> : <Trash2 />}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>¿Eliminar este clip?</AlertDialogTitle>
          <AlertDialogDescription>
            «{clip.hook || clip.title}»: se borran su video, su portada y su borrador del disco. El resto del proyecto no
            cambia. No se puede deshacer.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancelar</AlertDialogCancel>
          <AlertDialogAction onClick={remove}>Eliminar clip</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  return (
    <span
      className={cn(
        "font-condensed tabular inline-flex h-9 min-w-12 items-center justify-center rounded-full bg-primary px-3 text-[22px] leading-none font-bold text-primary-foreground shadow-[0_6px_16px_-6px_rgb(0_0_0/0.7)]",
        className,
      )}
      aria-label={`Puntaje ${score} de 100`}
    >
      {score}
    </span>
  );
}

function RenderState({ clip }: { clip: ClipDTO }) {
  if (clip.renderStatus === "RUNNING")
    return (
      <div className="flex flex-col gap-1.5" role="status">
        <span className="flex items-center gap-1.5 text-xs text-primary">
          <Loader2 className="size-3 animate-spin" /> Renderizando <span className="tabular">{clip.renderProgress} %</span>
        </span>
        <Progress value={clip.renderProgress} aria-label="Progreso del render" />
      </div>
    );
  if (clip.renderStatus === "QUEUED") return <Badge size="sm" className="self-start">En cola para render</Badge>;
  if (clip.renderStatus === "FAILED")
    return (
      <Badge variant="danger" size="sm" className="gap-1 self-start" title={clip.renderError ?? ""}>
        <AlertTriangle className="size-3" /> El render falló
      </Badge>
    );
  if (clip.renderStatus === "DONE" && clip.editRevision !== clip.renderedRevision)
    return (
      <Badge variant="yellow" size="sm" className="self-start" title="El MP4 y la portada son del render anterior: renderiza para ver los cambios">
        Cambios sin renderizar
      </Badge>
    );
  if (clip.renderStatus === "DONE" && clip.qaWarnings.length)
    return (
      <Badge variant="yellow" size="sm" className="gap-1 self-start" title={clip.qaWarnings.join("\n")}>
        <AlertTriangle className="size-3" /> {clip.qaWarnings.length} aviso(s) de calidad
      </Badge>
    );
  return null;
}

interface CardProps {
  clip: ClipDTO;
  onRender: (id: string) => void;
  /** Modo «combinar»: posición en la selección (1, 2…) o null. */
  selection?: { order: number | null; onToggle: () => void };
}

export function ClipCard({ clip, onRender, selection }: CardProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const rendered = clip.renderStatus === "DONE" && clip.videoUrl;
  return (
    <article className={cn("group relative flex flex-col rounded-[var(--r-card)] bg-card p-2", selection?.order && "ring-2 ring-primary ring-offset-4 ring-offset-background")}>
      {selection && (
        <label className="absolute top-4 right-4 z-10 flex cursor-pointer items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white">
          <Checkbox checked={selection.order != null} onCheckedChange={selection.onToggle} aria-label="Elegir para combinar" />
          {selection.order != null ? `#${selection.order}` : "Elegir"}
        </label>
      )}
      <Link
        href={`/clips/${clip.id}`}
        className="relative block aspect-[9/16] overflow-hidden rounded-[var(--r-card-sm)] bg-well outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onMouseEnter={() => videoRef.current?.play().catch(() => {})}
        onMouseLeave={() => {
          const v = videoRef.current;
          if (v) {
            v.pause();
            v.currentTime = 0;
          }
        }}
      >
        {rendered ? (
          <PausingVideo
            ref={videoRef}
            src={clip.videoUrl!}
            poster={clip.thumbUrl ?? undefined}
            muted
            loop
            playsInline
            preload="none"
            className={cn("size-full", clip.aspect === "vertical" ? "object-cover" : "object-contain")}
          />
        ) : (
          <div className="flex size-full flex-col justify-center gap-3 p-5 text-center">
            <p className="font-condensed text-xl leading-tight font-extrabold text-balance uppercase">{clip.hook}</p>
            <p className="text-xs text-muted-foreground">
              {clip.renderStatus === "NONE" ? "Sin renderizar" : "Preparando el video"}
            </p>
          </div>
        )}
        <ScoreBadge score={clip.score} className="absolute top-2.5 left-2.5" />
        {clip.order != null && (
          <span
            className="tabular absolute bottom-2.5 left-2.5 rounded-full bg-black/75 px-2 py-0.5 text-xs font-semibold text-white"
            title={`Publicar en el lugar ${clip.order}: el número va en el nombre del MP4 y de su portada`}
          >
            #{clip.order}
          </span>
        )}
        {rendered && (
          <Play className="absolute right-3 bottom-3 size-5 fill-white/90 text-white/90 opacity-80 transition-opacity group-hover:opacity-0" />
        )}
      </Link>
      <div className="mt-3 flex flex-1 flex-col gap-1.5 px-1.5 pb-1">
        <p className="line-clamp-2 text-[15px] leading-snug font-medium">{clip.hook || clip.title.replace(/\s*#Shorts\s*$/i, "")}</p>
        <p className="tabular text-xs text-muted-foreground">
          {clip.segmentCount > 1 ? `${clip.segmentCount} tramos` : `${timecode(clip.startSec)} a ${timecode(clip.endSec)}`},{" "}
          {Math.round(clip.durationSec)} s
          {clip.hookType && HOOK_TYPE_LABEL[clip.hookType] ? (
            <Badge size="sm" className="ml-1.5 align-middle">{HOOK_TYPE_LABEL[clip.hookType]}</Badge>
          ) : null}
        </p>
        <p className="text-[11px] text-muted-foreground" title="Fecha de creación del clip">
          Creado {new Date(clip.createdAt).toLocaleString("es", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
        </p>
        <RenderState clip={clip} />
        <div className="mt-auto flex gap-1.5 pt-2">
          <Button asChild size="sm" variant="secondary" className="flex-1">
            <Link href={`/clips/${clip.id}`}>
              <Pencil /> Editar
            </Link>
          </Button>
          {rendered ? (
            <SaveClipMenu clip={clip} />
          ) : (
            <Button
              size="sm"
              variant="outline"
              disabled={clip.renderStatus === "QUEUED" || clip.renderStatus === "RUNNING"}
              onClick={() => onRender(clip.id)}
            >
              Renderizar
            </Button>
          )}
          <DeleteClip clip={clip} />
        </div>
      </div>
    </article>
  );
}
