"use client";

import { Film, Link2, Upload } from "lucide-react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { useProjects } from "@/lib/client";
import { ACTIVE_STATUSES, duration, relativeDate } from "@/lib/format";
import type { ProjectDTO } from "@/lib/types";
import { PhaseBar, StatusBadge } from "./status";

function sourceLabel(p: ProjectDTO) {
  if (p.sourceType === "upload") return "Archivo subido";
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
        className="grid grid-cols-[96px_1fr] items-center gap-4 rounded-lg px-2 py-3 outline-none hover:bg-card focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[128px_1fr_auto]"
      >
        <div className="relative aspect-video overflow-hidden rounded-md bg-well">
          {p.thumbUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={p.thumbUrl} alt="" className="size-full object-cover" loading="lazy" />
          ) : (
            <Film className="absolute inset-0 m-auto size-5 text-muted-foreground" />
          )}
          {p.durationSec ? (
            <span className="tabular absolute right-1 bottom-1 rounded bg-black/70 px-1 text-[11px]">
              {duration(p.durationSec)}
            </span>
          ) : null}
        </div>
        <div className="min-w-0">
          <p className="truncate font-medium">{p.title || "Video sin título todavía"}</p>
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
            <p className="mt-1 text-xs text-muted-foreground">
              {p.clipCount} clips, {p.clipsRendered} renderizados
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
      <h2 id="projects-title" className="font-condensed text-xl font-bold">
        Proyectos
      </h2>
      {isLoading ? (
        <div className="mt-4 space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      ) : error ? (
        <p className="mt-4 text-sm text-destructive">No se pudo leer la base de datos: {(error as Error).message}</p>
      ) : !data?.length ? (
        <p className="mt-4 text-sm text-muted-foreground">
          Todavía no hay proyectos. Pega un enlace arriba para crear el primero.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {data.map((p) => (
            <Row key={p.id} p={p} />
          ))}
        </ul>
      )}
    </section>
  );
}
