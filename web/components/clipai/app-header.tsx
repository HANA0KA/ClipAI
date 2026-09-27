"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Eraser } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useHealth } from "@/lib/client";
import { llmLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function Wordmark() {
  return (
    <Link href="/" className="group flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {/* Un cuadro vertical 9:16: la unidad de todo lo que hace la app. */}
      <span aria-hidden className="relative block h-7 w-4 rounded-[3px] border-2 border-primary">
        <span className="absolute inset-x-[3px] bottom-[5px] h-[3px] rounded-full bg-primary" />
      </span>
      <span className="font-condensed text-2xl font-extrabold tracking-tight">ClipAI</span>
    </Link>
  );
}

function ServiceStatus() {
  const { data, isError } = useHealth();
  const down = isError || (data && !data.ok);
  const degraded = !down && data && (!data.libass || !data.deno);
  const tone = down ? "bg-destructive" : degraded ? "bg-primary" : data ? "bg-success" : "bg-muted-foreground";
  const label = down
    ? "Servicio local detenido"
    : !data
      ? "Conectando…"
      : data.llmConfigured
        ? data.llm?.startsWith("openai:")
          ? `IA local: ${llmLabel(data.llm).replace("local: ", "")}`
          : data.llm?.startsWith("vertex:")
            ? "IA: Gemini en Vertex"
            : "IA: Gemini"
        : "Sin IA: respaldo por señales";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex items-center gap-2 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
          <span className={cn("size-2 rounded-full", tone)} />
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs leading-relaxed">
        {down ? (
          <p>{data?.error ?? "FastAPI no responde en 127.0.0.1:8000. Arranca con ./start.sh."}</p>
        ) : data ? (
          <div className="space-y-1">
            <p>FFmpeg {data.libass ? "con" : "sin"} libass{data.libass ? "" : ": instala ffmpeg-full"}</p>
            <p>yt-dlp {data.ytdlp ?? "?"}{data.deno ? " con Deno" : ", falta Deno"}</p>
            <p>Transcripción {data.whisper}</p>
            <p>Disco libre {data.diskFreeGb} GB</p>
            {data.worker?.current && <p>Trabajando: {data.worker.current.type}</p>}
          </div>
        ) : null}
      </TooltipContent>
    </Tooltip>
  );
}

function CleanupButton() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      const r = await api<{ projects: number; freedMb: number }>("/api/cleanup", { method: "POST" });
      toast.success(r.projects ? `Liberados ${r.freedMb} MB de ${r.projects} proyecto(s)` : "No había videos fuente que borrar");
      qc.invalidateQueries();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="sm" disabled={busy}>
          <Eraser /> Limpiar
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>¿Borrar los videos fuente?</AlertDialogTitle>
          <AlertDialogDescription>
            Se borran source.mp4 y audio.wav de los proyectos terminados. Los clips renderizados y los trozos de
            cada clip se conservan: puedes cambiar subtítulos, plantilla o encuadre, pero no ampliar los bordes.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancelar</AlertDialogCancel>
          <AlertDialogAction onClick={run}>Borrar fuentes</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function AppHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6">
        <Wordmark />
        <div className="flex items-center gap-2">
          <ServiceStatus />
          <CleanupButton />
        </div>
      </div>
    </header>
  );
}
