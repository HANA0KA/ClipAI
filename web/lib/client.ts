"use client";

import { useQuery } from "@tanstack/react-query";
import { ACTIVE_STATUSES } from "@/lib/format";
import type { ClipDTO, ClipDetail, Health, ProjectDTO, TemplateInfo } from "@/lib/types";

export async function api<T = unknown>(url: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(url, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || `Error ${res.status}`);
  return data as T;
}

const busyClip = (c: ClipDTO) => c.renderStatus === "QUEUED" || c.renderStatus === "RUNNING" ||
  c.publishStatus === "QUEUED" || c.publishStatus === "RUNNING";

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: () => api<ProjectDTO[]>("/api/projects"),
    refetchInterval: (q) => (q.state.data?.some((p) => ACTIVE_STATUSES.includes(p.status)) ? 3000 : 15000),
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => api<{ project: ProjectDTO; clips: ClipDTO[] }>(`/api/projects/${id}`),
    // Consulta cada 3 s mientras procesa o renderiza (plan: progreso en vivo).
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return 3000;
      return ACTIVE_STATUSES.includes(d.project.status) || d.clips.some(busyClip) ? 3000 : false;
    },
  });
}

export function useClip(id: string) {
  return useQuery({
    queryKey: ["clip", id],
    queryFn: () => api<ClipDetail>(`/api/clips/${id}`),
    refetchInterval: (q) => (q.state.data && busyClip(q.state.data.clip) ? 3000 : false),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<Health>("/api/health"),
    refetchInterval: 15000,
  });
}

export function useTemplates() {
  return useQuery({ queryKey: ["templates"], queryFn: () => api<TemplateInfo[]>("/api/templates"), staleTime: Infinity });
}
