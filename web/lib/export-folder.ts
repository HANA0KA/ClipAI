"use client";

import { fileTitle } from "@/lib/publish-order";
import type { ClipDTO, ProjectDTO } from "@/lib/types";

// Descarga masiva de un proyecto a una carpeta que eliges: una subcarpeta con
// el nombre del proyecto y, en orden de publicación, cada video con su portada
// al lado («01 - Título.mp4», «01 - Título - portada.jpg») más un texto con
// título, descripción y hashtags de cada uno. Chrome y Edge dejan elegir la
// carpeta (File System Access API); en otros navegadores los archivos van a
// Descargas con los mismos nombres.

interface DirectoryPickerWindow {
  showDirectoryPicker?: (options?: { id?: string; mode?: "read" | "readwrite" }) => Promise<FileSystemDirectoryHandle>;
  showSaveFilePicker?: (options?: {
    id?: string; suggestedName?: string; types?: { description?: string; accept: Record<string, string[]> }[];
  }) => Promise<FileSystemFileHandle>;
}

export const INDEX_FILE = "00 - Orden de publicación.txt";

export function canPickFolder(): boolean {
  return typeof window !== "undefined" && typeof (window as DirectoryPickerWindow).showDirectoryPicker === "function";
}

export interface ExportItem {
  clip: ClipDTO;
  files: { name: string; url: string }[];
}

/** Clips con video listo, en orden de publicación, y sus archivos. */
export function exportPlan(clips: ClipDTO[]): { items: ExportItem[]; pending: ClipDTO[]; outdated: ClipDTO[] } {
  const ordered = [...clips].sort((a, b) => (a.order ?? Infinity) - (b.order ?? Infinity));
  const items: ExportItem[] = [];
  const pending: ClipDTO[] = [];
  for (const c of ordered) {
    if (c.renderStatus !== "DONE" || !c.downloadUrl) {
      pending.push(c);
      continue;
    }
    const files = [{ name: `${c.fileBase}.mp4`, url: c.downloadUrl }];
    if (c.coverDownloadUrl) files.push({ name: `${c.fileBase} - portada.jpg`, url: c.coverDownloadUrl });
    items.push({ clip: c, files });
  }
  const outdated = items.map((i) => i.clip).filter((c) => c.editRevision !== c.renderedRevision);
  return { items, pending, outdated };
}

/** Texto con lo que hay que pegar al publicar cada clip, en orden. */
export function indexText(project: ProjectDTO, items: ExportItem[]): string {
  const lines = [
    `${project.title ?? "Proyecto"}`,
    "Orden de publicación (el 01 va primero). Cada video tiene su portada al lado.",
    "",
  ];
  for (const { clip, files } of items) {
    lines.push(`${clip.fileBase}`);
    lines.push(`  Video: ${files[0].name}`);
    if (files[1]) lines.push(`  Portada: ${files[1].name}`);
    lines.push(`  Título y descripción: ${clip.hook || clip.title}`);
    if (clip.hashtags.trim()) lines.push(`  Hashtags: ${clip.hashtags.trim()}`);
    lines.push("");
  }
  return lines.join("\n");
}

async function writeUrl(dir: FileSystemDirectoryHandle, name: string, url: string) {
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`No se pudo leer «${name}» (error ${res.status})`);
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  // En flujo: un MP4 de cientos de MB no pasa entero por la memoria. Si se
  // corta a medias, el archivo no se guarda (el navegador descarta lo escrito).
  await res.body.pipeTo(writable);
}

async function writeText(dir: FileSystemDirectoryHandle, name: string, text: string) {
  const handle = await dir.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  await writable.write(new Blob([text], { type: "text/plain;charset=utf-8" }));
  await writable.close();
}

/**
 * Pide la carpeta y guarda todo. Devuelve null si cancelaste la elección.
 * ``onProgress(hechos, total)`` por archivo.
 */
export async function exportToFolder(project: ProjectDTO, items: ExportItem[],
  onProgress: (done: number, total: number) => void): Promise<{ folder: string; files: number } | null> {
  const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
  if (!picker) throw new Error("Este navegador no deja elegir una carpeta.");
  let root: FileSystemDirectoryHandle;
  try {
    root = await picker.call(window, { id: "clipai-export", mode: "readwrite" });
  } catch (e) {
    if ((e as Error).name === "AbortError") return null;
    throw e;
  }
  const folder = fileTitle(project.title ?? "", "Proyecto");
  const dir = await root.getDirectoryHandle(folder, { create: true });
  const all = items.flatMap((i) => i.files);
  let done = 0;
  onProgress(done, all.length);
  for (const f of all) {
    await writeUrl(dir, f.name, f.url);
    onProgress(++done, all.length);
  }
  await writeText(dir, INDEX_FILE, indexText(project, items));
  return { folder: `${root.name}/${folder}`, files: all.length + 1 };
}

/** Sin elegir carpeta: descarga uno a uno (a Descargas) con los mismos nombres. */
export async function downloadOneByOne(items: ExportItem[], onProgress: (done: number, total: number) => void) {
  const all = items.flatMap((i) => i.files);
  for (let i = 0; i < all.length; i++) {
    downloadLink(all[i].url, all[i].name);
    onProgress(i + 1, all.length);
    await new Promise((r) => setTimeout(r, 700)); // el navegador bloquea ráfagas de descargas
  }
}

const isAbort = (e: unknown) => (e as Error)?.name === "AbortError";

/** «Guardar como…» de una carpeta y un nombre a tu gusto (Chrome y Edge). */
export const canSaveAs = () => typeof window !== "undefined" && typeof (window as DirectoryPickerWindow).showSaveFilePicker === "function";

/**
 * Guarda un archivo donde elijas y con el nombre que quieras (el gancho por
 * defecto). Sin «Guardar como» en el navegador, lo descarga a Descargas con
 * ese nombre. Devuelve false si cancelaste.
 */
export async function saveFileAs(url: string, name: string, kind: "video" | "image"): Promise<boolean> {
  const picker = (window as DirectoryPickerWindow).showSaveFilePicker;
  if (!picker) {
    downloadLink(url, name);
    return true;
  }
  let handle: FileSystemFileHandle;
  try {
    // Primero el selector (necesita el clic reciente); la descarga va después.
    handle = await picker.call(window, {
      id: kind === "video" ? "clipai-video" : "clipai-cover",
      suggestedName: name,
      types: [kind === "video"
        ? { description: "Video MP4", accept: { "video/mp4": [".mp4"] } }
        : { description: "Imagen JPG", accept: { "image/jpeg": [".jpg", ".jpeg"] } }],
    });
  } catch (e) {
    if (isAbort(e)) return false;
    throw e;
  }
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`No se pudo leer «${name}» (error ${res.status})`);
  await res.body.pipeTo(await handle.createWritable());
  return true;
}

/** Video y portada de un clip juntos, en la carpeta que elijas. Devuelve su nombre, o null si cancelaste. */
export async function saveClipToFolder(clip: ClipDTO): Promise<string | null> {
  const files = [
    ...(clip.downloadUrl ? [{ name: `${clip.fileBase}.mp4`, url: clip.downloadUrl }] : []),
    ...(clip.coverDownloadUrl ? [{ name: `${clip.fileBase} - portada.jpg`, url: clip.coverDownloadUrl }] : []),
  ];
  const picker = (window as DirectoryPickerWindow).showDirectoryPicker;
  if (!picker) {
    for (const f of files) {
      downloadLink(f.url, f.name);
      await new Promise((r) => setTimeout(r, 700)); // el navegador bloquea ráfagas de descargas
    }
    return "Descargas";
  }
  let dir: FileSystemDirectoryHandle;
  try {
    dir = await picker.call(window, { id: "clipai-save", mode: "readwrite" });
  } catch (e) {
    if (isAbort(e)) return null;
    throw e;
  }
  for (const f of files) await writeUrl(dir, f.name, f.url);
  return dir.name;
}

function downloadLink(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
