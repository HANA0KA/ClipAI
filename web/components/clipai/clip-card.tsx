"use client";

import { AlertTriangle, Download, Loader2, Pencil, Play } from "lucide-react";
import Link from "next/link";
import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { timecode } from "@/lib/format";
import type { ClipDTO } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  return (
    <span
      className={cn(
        "font-condensed tabular inline-flex min-w-11 items-center justify-center rounded-md bg-primary px-1.5 text-2xl leading-8 font-extrabold text-primary-foreground",
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
      <span className="flex items-center gap-1.5 text-xs text-primary">
        <Loader2 className="size-3 animate-spin" /> Renderizando
      </span>
    );
  if (clip.renderStatus === "QUEUED") return <span className="text-xs text-muted-foreground">En cola para render</span>;
  if (clip.renderStatus === "FAILED")
    return (
      <span className="flex items-center gap-1.5 text-xs text-destructive" title={clip.renderError ?? ""}>
        <AlertTriangle className="size-3" /> El render falló
      </span>
    );
  if (clip.renderStatus === "DONE" && clip.qaWarnings.length)
    return (
      <span className="flex items-center gap-1.5 text-xs text-primary" title={clip.qaWarnings.join("\n")}>
        <AlertTriangle className="size-3" /> {clip.qaWarnings.length} aviso(s) de calidad
      </span>
    );
  return null;
}

export function ClipCard({ clip, onRender }: { clip: ClipDTO; onRender: (id: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dur = clip.endSec - clip.startSec;
  const rendered = clip.renderStatus === "DONE" && clip.videoUrl;
  return (
    <article className="group flex flex-col">
      <Link
        href={`/clips/${clip.id}`}
        className="relative block aspect-[9/16] overflow-hidden rounded-xl bg-well outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
          <video
            ref={videoRef}
            src={clip.videoUrl!}
            poster={clip.thumbUrl ?? undefined}
            muted
            loop
            playsInline
            preload="none"
            className="size-full object-cover"
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
        {rendered && (
          <Play className="absolute right-3 bottom-3 size-5 fill-white/90 text-white/90 opacity-80 transition-opacity group-hover:opacity-0" />
        )}
      </Link>
      <div className="mt-2.5 flex flex-1 flex-col gap-1">
        <p className="line-clamp-2 text-sm leading-snug font-medium">{clip.title.replace(/\s*#Shorts\s*$/i, "")}</p>
        <p className="tabular text-xs text-muted-foreground">
          {timecode(clip.startSec)} a {timecode(clip.endSec)}, {Math.round(dur)} s
        </p>
        <RenderState clip={clip} />
        <div className="mt-auto flex gap-1.5 pt-2">
          <Button asChild size="sm" variant="secondary" className="flex-1">
            <Link href={`/clips/${clip.id}`}>
              <Pencil /> Editar
            </Link>
          </Button>
          {rendered ? (
            <Button asChild size="sm" variant="outline" aria-label="Descargar MP4">
              <a href={clip.downloadUrl!} download>
                <Download />
              </a>
            </Button>
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
        </div>
      </div>
    </article>
  );
}
