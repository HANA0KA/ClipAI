"use client";

import { Film, Link2, Upload } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Empty, EmptyDescription, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/lib/client";
import { ACTIVE_STATUSES, duration, relativeDate } from "@/lib/format";
import { formatClock } from "@/lib/sources";
import type { ProjectDTO } from "@/lib/types";
import { PhaseBar, StatusBadge } from "./status";

function sourceLabel(p: ProjectDTO) {
  if (p.sourceType === "upload") return "Archivo subido";
  if (p.sourceType === "kick") {
    const ch = /kick\.com\/([^/?#]+)/.exec(p.sourceUrl ?? "")?.[1];
    const span = p.rangeEndSec != null ? ` · tramo ${formatClock(p.rangeStartSec ?? 0)} – ${formatClock(p.rangeEndSec)}` : "";
    return `Kick${ch && ch !== "video" ? ` · ${ch}` : ""}${span}`;
  }
  try {
    const u = new URL(p.sourceUrl ?? "");
    return u.hostname.replace("www.", "") + (u.searchParams.get("v") ? `/${u.searchParams.get("v")}` : u.pathname);
  } catch {
    return p.sourceUrl ?? "";
  }
}

function Row({ p }: { p: ProjectDTO }) {
  const active = ACTIVE_STATUSES.includes(p.status);
  return (
    <li>
      <Link
        href={`/projects/${p.id}`}
        className="grid grid-cols-[96px_1fr] items-center gap-4 rounded-[var(--r-card-sm)] bg-card p-3 pr-4 outline-none transition-colors hover:bg-[var(--v-beige)] focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[136px_1fr_auto]"
      >
        <div className="relative aspect-video overflow-hidden rounded-[var(--r-md)] bg-well">
          {p.thumbUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={p.thumbUrl} alt="" className="size-full object-cover" loading="lazy" />
          ) : (
            <Film className="absolute inset-0 m-auto size-5 text-muted-foreground" />
          )}
          {p.durationSec ? (
            <span className="tabular absolute right-1.5 bottom-1.5 rounded-full bg-black/70 px-1.5 py-px text-[11px] font-medium">
              {duration(p.durationSec)}
            </span>
          ) : null}
        </div>
        <div className="min-w-0">
          <p className="truncate text-[15px] font-medium">{p.title || "Video sin título todavía"}</p>
          <p className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
            {p.sourceType === "upload" ? <Upload className="size-3" /> : <Link2 className="size-3" />}
            <span className="truncate">{sourceLabel(p)}</span>
          </p>
          {active ? (
            <div className="mt-2 max-w-md">
              <PhaseBar project={p} compact />
              <p className="mt-1 truncate text-xs text-muted-foreground">{p.stage}</p>
            </div>
          ) : p.status === "READY" ? (
            <p className="mt-2 flex flex-wrap gap-1.5">
              <Badge size="sm">{p.clipCount} {p.clipCount === 1 ? "clip" : "clips"}</Badge>
              <Badge size="sm" variant={p.clipsRendered === p.clipCount ? "olive" : "default"}>
                {p.clipsRendered} {p.clipsRendered === 1 ? "renderizado" : "renderizados"}
              </Badge>
            </p>
          ) : p.error ? (
            <p className="mt-1 truncate text-xs text-destructive">{p.error}</p>
          ) : null}
        </div>
        <div className="col-span-2 flex items-center gap-3 sm:col-span-1 sm:flex-col sm:items-end">
          <StatusBadge status={p.status} />
          <span className="text-xs text-muted-foreground">{relativeDate(p.createdAt)}</span>
        </div>
      </Link>
    </li>
  );
}

export function ProjectList() {
  const { data, isLoading, error } = useProjects();
  return (
    <section className="mt-10" aria-labelledby="projects-title">
      <div className="flex items-baseline gap-3">
        <h2 id="projects-title" className="font-condensed text-2xl font-bold">
          Proyectos
        </h2>
        {data?.length ? <Badge variant="count">{data.length}</Badge> : null}
      </div>
      {isLoading ? (
        <div className="mt-4 space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[88px] w-full rounded-[var(--r-card-sm)]" />
          ))}
        </div>
      ) : error ? (
        <p className="mt-4 text-sm text-destructive">No se pudo leer la base de datos: {(error as Error).message}</p>
      ) : !data?.length ? (
        <Empty className="mt-4 rounded-[var(--r-card)] bg-card">
          <EmptyTitle>Todavía no hay proyectos</EmptyTitle>
          <EmptyDescription>Pega un enlace de YouTube o de Kick arriba, o suelta un video, para crear el primero.</EmptyDescription>
        </Empty>
      ) : (
        <ul className="mt-4 space-y-2">
          {data.map((p) => (
            <Row key={p.id} p={p} />
          ))}
        </ul>
      )}
    </section>
  );
}
