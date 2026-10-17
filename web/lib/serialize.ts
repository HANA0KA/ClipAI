import "server-only";
import fs from "node:fs";
import path from "node:path";
import type { Clip, Project } from "@/lib/generated/prisma/client";
import { legacySegments, normalizeDoc, totalDuration } from "@/lib/edit-doc";
import { projectDir } from "@/lib/paths";
import { fileBase, publishPositions } from "@/lib/publish-order";
import type { ClipDTO, CoverSettings, ProjectDTO } from "@/lib/types";

/** Ruta relativa a data/ ("projects/<id>/…") → URL servida por FastAPI vía /media. */
export function mediaUrl(rel: string | null | undefined, version?: Date | string): string | null {
  if (!rel) return null;
  const v = version ? `?v=${new Date(version).getTime()}` : "";
  return `/media/files/${rel.split(path.sep).map(encodeURIComponent).join("/")}${v}`;
}

const COVER_DEFAULTS: CoverSettings = { text: null, time: null, position: "center", style: "outline", dim: true };

/** Misma normalización que media/services/cover.py `parse`. */
function coverSettings(raw: string | null | undefined): CoverSettings {
  const d = parseJson<Partial<CoverSettings>>(raw, {});
  return {
    text: typeof d.text === "string" && d.text.trim() ? d.text : null,
    time: typeof d.time === "number" && d.time >= 0 ? d.time : null,
    position: d.position === "top" || d.position === "bottom" ? d.position : COVER_DEFAULTS.position,
    style: d.style === "box" ? "box" : COVER_DEFAULTS.style,
    dim: typeof d.dim === "boolean" ? d.dim : COVER_DEFAULTS.dim,
  };
}

function parseJson<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function projectDTO(p: Project, clips: Pick<Clip, "renderStatus">[] = []): ProjectDTO {
  const hasSource = !p.sourceDeleted && fs.existsSync(path.join(projectDir(p.id), "source.mp4"));
  return {
    id: p.id,
    sourceType: p.sourceType as ProjectDTO["sourceType"],
    sourceUrl: p.sourceUrl,
    title: p.title,
    durationSec: p.durationSec,
    language: p.language,
    status: p.status as ProjectDTO["status"],
    progress: p.progress,
    stage: p.stage,
    error: p.error,
    query: p.query,
    transcriptSource: p.transcriptSource,
    llmProvider: p.llmProvider,
    thumbUrl: mediaUrl(p.thumbPath),
    sourceVideoUrl: hasSource ? mediaUrl(`projects/${p.id}/source.mp4`) : null,
    sourceDeleted: p.sourceDeleted,
    aiCostUsd: p.aiCostUsd,
    aiTokens: p.aiTokens,
    aiCostEstimated: p.aiCostEstimated,
    templateId: p.templateId,
    rangeStartSec: p.rangeStartSec,
    rangeEndSec: p.rangeEndSec,
    createdAt: p.createdAt.toISOString(),
    clipCount: clips.length,
    clipsRendered: clips.filter((c) => c.renderStatus === "DONE").length,
  };
}

/** Documento de edición del clip (tramos, encuadre…), completo y validado. */
export function clipDoc(c: Clip) {
  return normalizeDoc(c.edit, legacySegments(c));
}

/** Posición de publicación de cada clip del proyecto (y cuántos hay). */
export interface ClipOrder {
  positions: Map<string, number>;
  total: number;
}

export function clipOrder(clips: Pick<Clip, "id" | "createdAt" | "rank" | "score">[]): ClipOrder {
  return { positions: publishPositions(clips), total: clips.length };
}

export function clipDTO(c: Clip, order?: ClipOrder): ClipDTO {
  const done = c.renderStatus === "DONE" && !!c.outputPath;
  const doc = clipDoc(c);
  const position = order?.positions.get(c.id) ?? null;
  const base = fileBase(position, c.hook || c.title, order?.total); // el gancho es título, descripción y nombre del archivo
  const name = `name=${encodeURIComponent(base)}`;
  return {
    id: c.id,
    projectId: c.projectId,
    rank: c.rank,
    startSec: c.startSec,
    endSec: c.endSec,
    score: c.score,
    reason: c.reason,
    hook: c.hook,
    hookType: c.hookType,
    title: c.title,
    description: c.description,
    hashtags: c.hashtags,
    hashtagSets: parseJson(c.hashtagSets, null),
    templateId: c.templateId,
    layoutMode: c.layoutMode as ClipDTO["layoutMode"],
    smartCut: c.smartCut,
    prependBestLine: c.prependBestLine,
    durationSec: Math.round(totalDuration(doc.segments) * 10) / 10,
    segmentCount: doc.segments.length,
    aspect: doc.framing.aspect,
    bestLine: c.bestLine,
    bestLineStart: c.bestLineStart,
    bestLineEnd: c.bestLineEnd,
    renderStatus: c.renderStatus as ClipDTO["renderStatus"],
    renderError: c.renderError,
    renderProgress: c.renderProgress,
    editRevision: c.editRevision,
    renderedRevision: c.renderedRevision,
    videoUrl: done ? mediaUrl(c.outputPath, c.updatedAt) : null,
    thumbUrl: done ? mediaUrl(c.thumbPath, c.updatedAt) : null,
    downloadUrl: done ? `/media/download/clip/${c.id}?${name}` : null,
    coverUrl: mediaUrl(c.coverPath, c.updatedAt),
    coverDownloadUrl: c.coverPath ? `/media/download/cover/${c.id}?v=${c.updatedAt.getTime()}&${name}` : null,
    cover: coverSettings(c.cover),
    qaWarnings: parseJson<string[]>(c.qaWarnings, []),
    signals: parseJson(c.signals, {}),
    publishStatus: c.publishStatus,
    publishInfo: parseJson(c.publishInfo, null),
    postedAt: c.postedAt ? c.postedAt.toISOString() : null,
    createdAt: c.createdAt.toISOString(),
    updatedAt: c.updatedAt.toISOString(),
    order: position,
    fileBase: base,
  };
}
