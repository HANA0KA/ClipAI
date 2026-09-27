import "server-only";
import fs from "node:fs";
import path from "node:path";
import type { Clip, Project } from "@/lib/generated/prisma/client";
import { projectDir } from "@/lib/paths";
import type { ClipDTO, ProjectDTO } from "@/lib/types";

/** Ruta relativa a data/ ("projects/<id>/…") → URL servida por FastAPI vía /media. */
export function mediaUrl(rel: string | null | undefined, version?: Date | string): string | null {
  if (!rel) return null;
  const v = version ? `?v=${new Date(version).getTime()}` : "";
  return `/media/files/${rel.split(path.sep).map(encodeURIComponent).join("/")}${v}`;
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
    createdAt: p.createdAt.toISOString(),
    clipCount: clips.length,
    clipsRendered: clips.filter((c) => c.renderStatus === "DONE").length,
  };
}

export function clipDTO(c: Clip): ClipDTO {
  const done = c.renderStatus === "DONE" && !!c.outputPath;
  return {
    id: c.id,
    projectId: c.projectId,
    rank: c.rank,
    startSec: c.startSec,
    endSec: c.endSec,
    score: c.score,
    reason: c.reason,
    hook: c.hook,
    title: c.title,
    description: c.description,
    hashtags: c.hashtags,
    templateId: c.templateId,
    layoutMode: c.layoutMode as ClipDTO["layoutMode"],
    smartCut: c.smartCut,
    prependBestLine: c.prependBestLine,
    bestLine: c.bestLine,
    bestLineStart: c.bestLineStart,
    bestLineEnd: c.bestLineEnd,
    renderStatus: c.renderStatus as ClipDTO["renderStatus"],
    renderError: c.renderError,
    videoUrl: done ? mediaUrl(c.outputPath, c.updatedAt) : null,
    thumbUrl: done ? mediaUrl(c.thumbPath, c.updatedAt) : null,
    downloadUrl: done ? `/media/download/clip/${c.id}` : null,
    qaWarnings: parseJson<string[]>(c.qaWarnings, []),
    signals: parseJson(c.signals, {}),
    publishStatus: c.publishStatus,
    publishInfo: parseJson(c.publishInfo, null),
    tiktokDraft: c.tiktokDraft,
    postedAt: c.postedAt ? c.postedAt.toISOString() : null,
    updatedAt: c.updatedAt.toISOString(),
  };
}
