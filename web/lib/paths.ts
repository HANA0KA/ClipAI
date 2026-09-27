import path from "node:path";
import { loadEnvConfig } from "@next/env";

// Raíz del proyecto (web/ está un nivel más abajo). El .env compartido vive ahí.
export const ROOT_DIR = path.resolve(process.cwd(), "..");
loadEnvConfig(ROOT_DIR);

export const DATA_DIR = path.resolve(ROOT_DIR, process.env.DATA_DIR || "./data");
export const PROJECTS_DIR = path.join(DATA_DIR, "projects");
export const MEDIA_API_URL = (process.env.MEDIA_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export function databaseFile(): string {
  const raw = process.env.DATABASE_URL;
  if (raw && raw.startsWith("file:")) {
    const file = raw.slice("file:".length);
    return path.isAbsolute(file) ? file : path.resolve(ROOT_DIR, file);
  }
  return path.join(DATA_DIR, "app.db");
}

export function projectDir(projectId: string): string {
  return path.join(PROJECTS_DIR, safeId(projectId));
}

export function clipDir(projectId: string, clipId: string): string {
  return path.join(projectDir(projectId), "clips", safeId(clipId));
}

/** Los ids son cuid: solo letras y dígitos. Evita rutas fuera de data/. */
export function safeId(id: string): string {
  if (!/^[a-z0-9]{8,40}$/i.test(id)) throw new Error("id inválido");
  return id;
}
