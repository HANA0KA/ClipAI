"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { Favorite, FavPlatform, Favorites } from "@/lib/favorites";
import { ACTIVE_STATUSES } from "@/lib/format";
import type { NetworkTags, TagNetwork } from "@/lib/network-tags";
import type { GlossaryRule } from "@/lib/glossary";
import type {
  ClipDTO, ClipDetail, FontInfo, Health, ProjectDTO, PublishText, SourceInfo, TemplateInfo, TimelineAssets, TrendingResponse,
} from "@/lib/types";

/** Error de la API con su código HTTP (409 = el clip se editó en otra pestaña). */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function api<T = unknown>(url: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(url, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((data as { error?: string }).error || `Error ${res.status}`, res.status);
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
    // Consulta cada 3 s mientras procesa o renderiza.
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
    // Más seguido mientras renderiza, para ver el avance.
    refetchInterval: (q) => {
      const c = q.state.data?.clip;
      if (!c) return false;
      return c.renderStatus === "RUNNING" ? 1500 : busyClip(c) ? 3000 : false;
    },
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

export function useFonts() {
  return useQuery({ queryKey: ["fonts"], queryFn: () => api<FontInfo[]>("/api/fonts"), staleTime: 60_000 });
}

/** Miniaturas y forma de onda del video fuente entre start y end. */
export function useTimeline(clipId: string, start: number, end: number, enabled: boolean) {
  return useQuery({
    queryKey: ["timeline", clipId, start, end],
    queryFn: () => api<TimelineAssets>(`/api/clips/${clipId}/timeline?start=${start}&end=${end}`),
    enabled: enabled && end > start,
    staleTime: Infinity,
    // Al cambiar el rango, la tira anterior sigue a la vista hasta que llega la nueva.
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

export function useGlossary() {
  return useQuery({
    queryKey: ["glossary"],
    queryFn: async () => (await api<{ rules: GlossaryRule[] }>("/api/glossary")).rules,
    staleTime: 60_000,
  });
}

export interface TrendingParams {
  q: string;
  period: "day" | "week" | "month";
  sort: "views" | "date";
  duration: "long" | "medium" | "any";
  /** Idioma hablado: «auto» = el de TRENDING_LANG, «any» = todos, o un código («es», «en»…). */
  lang: string;
}

export const trendingUrl = (params: TrendingParams, refresh = false) =>
  `/api/trending?${new URLSearchParams({ ...params, ...(refresh ? { refresh: "1" } : {}) })}`;

/** Tendencias con potencial para clips. La primera vez tarda unos segundos (lee la ficha de cada video); luego, caché de 30 min. */
export function useTrending(params: TrendingParams) {
  return useQuery({
    queryKey: ["trending", params],
    queryFn: () => api<TrendingResponse>(trendingUrl(params)),
    staleTime: 30 * 60_000,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

/** Ficha de un enlace de Kick o de YouTube (video o canal) antes de crear el proyecto; `tab`: pestaña de un canal de YouTube. */
export function useSourceInfo(url: string, enabled: boolean, tab: "videos" | "streams" = "videos") {
  return useQuery({
    queryKey: ["source-info", url, tab],
    queryFn: () => api<SourceInfo>(`/api/source-info?url=${encodeURIComponent(url)}${tab === "streams" ? "&tab=streams" : ""}`),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/** Streamers de Kick y canales de YouTube guardados como botones (data/favorites.json). */
export function useFavorites() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["favorites"], queryFn: () => api<Favorites>("/api/favorites"), staleTime: 60_000 });
  const save = (data: Favorites) => qc.setQueryData(["favorites"], data);
  const add = useMutation({
    mutationFn: ({ platform, favorite }: { platform: FavPlatform; favorite: Favorite }) =>
      api<Favorites>("/api/favorites", { method: "POST", json: { platform, ...favorite } }),
    onSuccess: save,
  });
  const remove = useMutation({
    mutationFn: ({ platform, key }: { platform: FavPlatform; key: string }) =>
      api<Favorites>(`/api/favorites?${new URLSearchParams({ platform, key })}`, { method: "DELETE" }),
    onSuccess: save,
  });
  return { favorites: query.data, isLoading: query.isLoading, add, remove };
}

/** Hashtags fijos de YouTube e Instagram para todos los videos; `save` los cambia y se ven al instante en cada clip. */
export function useNetworkTags() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["network-tags"], queryFn: () => api<NetworkTags>("/api/network-hashtags"), staleTime: 60_000 });
  const save = useMutation({
    mutationFn: (patch: Partial<Record<TagNetwork, string>>) =>
      api<NetworkTags>("/api/network-hashtags", { method: "PUT", json: patch }),
    onSuccess: (data) => qc.setQueryData(["network-tags"], data),
  });
  return { tags: query.data, isLoading: query.isLoading, save };
}

/** Título, descripción y hashtags para publicar (con el creador); se recalcula al editar el gancho, tras una pausa. */
export function usePublishText(clipId: string, hook: string, hashtags: string) {
  const [typed, setTyped] = useState({ hook, hashtags });
  useEffect(() => {
    const t = setTimeout(() => setTyped({ hook, hashtags }), 350);
    return () => clearTimeout(t);
  }, [hook, hashtags]);
  return useQuery({
    queryKey: ["publish-text", clipId, typed.hook, typed.hashtags],
    queryFn: () => api<PublishText>(`/api/clips/${clipId}/publish-text`, { method: "POST", json: typed }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  });
}
