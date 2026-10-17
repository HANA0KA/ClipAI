"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Eraser, TrendingUp } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useHealth } from "@/lib/client";
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

/**
 * Estado de los servicios locales. Con todo en orden es solo un punto verde (el
 * detalle sale al pasar el cursor); si algo falla —servicio detenido, FFmpeg sin
 * libass, sin Deno o sin IA configurada— dice qué, para que se note.
 */
function ServiceStatus() {
  const { data, isError } = useHealth();
  const down = isError || (data && !data.ok);
  const degraded = !down && data && (!data.libass || !data.deno);
  const noAi = !down && data && !data.llmConfigured;
  const tone = down ? "bg-destructive" : degraded || noAi ? "bg-primary" : data ? "bg-success" : "bg-muted-foreground";
  const problem = down
    ? "Servicio local detenido"
    : degraded
      ? !data?.libass ? "FFmpeg sin libass" : "Falta Deno"
      : noAi
        ? "Sin IA: respaldo por señales"
        : null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn("flex items-center gap-2 rounded-full text-xs text-muted-foreground", problem && "border border-border px-3 py-1")}
          role="status"
          aria-label={problem ?? (data ? "Servicios locales en orden" : "Conectando con los servicios locales")}
        >
          <span className={cn("size-2 rounded-full", tone)} />
          {problem}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs leading-relaxed">
        {down ? (
          <p>{data?.error ?? "FastAPI no responde en 127.0.0.1:8000. Arranca con ./start.sh."}</p>
        ) : data ? (
          <div className="space-y-1">
            <p>{problem ?? "Servicios locales en orden"}</p>
            <p>FFmpeg {data.libass ? "con" : "sin"} libass{data.libass ? "" : ": instala ffmpeg-full"}</p>
            <p>yt-dlp {data.ytdlp ?? "?"}{data.deno ? " con Deno" : ", falta Deno"}</p>
            <p>Transcripción {data.whisper}</p>
            <p>Disco libre {data.diskFreeGb} GB</p>
            {data.worker?.current && <p>Trabajando: {data.worker.current.type}</p>}
          </div>
        ) : (
          <p>Conectando…</p>
        )}
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
  const pathname = usePathname();
  const trending = pathname.startsWith("/tendencias");
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-5">
          <Wordmark />
          <nav aria-label="Principal" className="flex items-center gap-1">
            <Button asChild variant={trending ? "secondary" : "ghost"} size="sm">
              <Link href="/tendencias" aria-current={trending ? "page" : undefined}><TrendingUp /> Tendencias</Link>
            </Button>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ServiceStatus />
          <CleanupButton />
        </div>
      </div>
    </header>
  );
}
