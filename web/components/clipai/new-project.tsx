"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileVideo, Loader2, Search, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/client";
import type { ProjectDTO } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".mp4,.mov,.m4v,.mkv,.webm,video/*";

function uploadFile(projectId: string, file: File, onProgress: (f: number) => void): Promise<void> {
  // XHR y no fetch: da progreso de subida para archivos de varios GB.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/projects/${projectId}/upload?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status < 300) return resolve();
      try {
        reject(new Error(JSON.parse(xhr.responseText).error));
      } catch {
        reject(new Error(`Error ${xhr.status} al subir`));
      }
    };
    xhr.onerror = () => reject(new Error("La subida se interrumpió"));
    xhr.send(file);
  });
}

export function NewProject() {
  const router = useRouter();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [showQuery, setShowQuery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null);

  async function fromUrl(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    try {
      const p = await api<ProjectDTO>("/api/projects", { method: "POST", json: { url, query } });
      qc.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${p.id}`);
    } catch (err) {
      toast.error((err as Error).message);
      setBusy(false);
    }
  }

  async function fromFile(file: File) {
    setBusy(true);
    setUpload({ name: file.name, progress: 0 });
    try {
      const p = await api<ProjectDTO>("/api/projects", {
        method: "POST",
        json: { sourceType: "upload", fileName: file.name, query },
      });
      await uploadFile(p.id, file, (f) => setUpload({ name: file.name, progress: f }));
      qc.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${p.id}`);
    } catch (err) {
      toast.error((err as Error).message);
      setUpload(null);
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Nuevo proyecto"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const f = e.dataTransfer.files?.[0];
        if (f && !busy) fromFile(f);
      }}
      className={cn(
        "relative rounded-xl border border-border bg-card px-5 py-8 transition-colors sm:px-10 sm:py-12",
        dragging && "border-primary bg-primary/5",
      )}
    >
      <h1 className="font-condensed max-w-3xl text-4xl leading-[1.05] font-extrabold tracking-tight text-balance sm:text-5xl">
        De un video largo a clips verticales listos para subir
      </h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">
        Pega un enlace de YouTube o suelta un archivo. ClipAI busca los mejores momentos de 30 a 90 segundos, los
        reencuadra en 9:16 y les pone subtítulos.
      </p>

      <form onSubmit={fromUrl} className="mt-8 flex max-w-3xl flex-col gap-3 sm:flex-row">
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=…"
          aria-label="Enlace de YouTube"
          disabled={busy}
          className="h-12 flex-1 text-base"
          autoFocus
        />
        <Button type="submit" size="lg" className="h-12 px-6 text-base" disabled={busy || !url.trim()}>
          {busy && !upload ? <Loader2 className="animate-spin" /> : null}
          Crear clips
        </Button>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 underline-offset-4 hover:text-foreground hover:underline disabled:opacity-50"
        >
          <Upload className="size-4" /> Subir un archivo MP4 o MOV
        </button>
        <button
          type="button"
          onClick={() => setShowQuery((v) => !v)}
          className="inline-flex items-center gap-1.5 underline-offset-4 hover:text-foreground hover:underline"
          aria-expanded={showQuery}
        >
          <Search className="size-4" /> Buscar un momento concreto
        </button>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) fromFile(f);
            e.target.value = "";
          }}
        />
      </div>

      {showQuery && (
        <div className="mt-4 max-w-3xl">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Por ejemplo: el momento donde habla de dinero"
            aria-label="Momento a buscar"
            maxLength={200}
          />
          <p className="mt-1.5 text-xs text-muted-foreground">
            Los clips que cumplen esta descripción aparecen primero.
          </p>
        </div>
      )}

      {upload && (
        <div className="mt-6 flex max-w-3xl items-center gap-3 text-sm">
          <FileVideo className="size-4 shrink-0 text-primary" />
          <span className="truncate">{upload.name}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary transition-[width]" style={{ width: `${upload.progress * 100}%` }} />
          </div>
          <span className="tabular w-10 text-right text-muted-foreground">{Math.round(upload.progress * 100)}%</span>
        </div>
      )}

      {dragging && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-xl text-lg font-semibold text-primary">
          Suelta el video para empezar
        </div>
      )}
    </section>
  );
}
