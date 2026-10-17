"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Captions, FileVideo, Link2, Loader2, Scissors, Search, TrendingUp, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input, InputControl, InputWrapper } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, useHealth, useSourceInfo, useTemplates } from "@/lib/client";
import { timecode } from "@/lib/format";
import { parseClock, parseSource } from "@/lib/sources";
import type { ProjectDTO } from "@/lib/types";
import { cn } from "@/lib/utils";
import { cssFont } from "./editor/template-picker";
import { type PanelTab, SourcePanel } from "./source-panel";
import { checkRange, SourcePreview } from "./source-preview";

const ACCEPT = ".mp4,.mov,.m4v,.mkv,.webm,video/*";
const AUTO = "__auto__";

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
  const { data: health } = useHealth();
  const { data: templates } = useTemplates();
  const [template, setTemplate] = useState(AUTO);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [checked, setChecked] = useState(""); // el enlace, tras una pausa al escribir (no se consulta a Kick en cada tecla)
  const templateId = template === AUTO ? null : template;
  const fileRef = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [showQuery, setShowQuery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [upload, setUpload] = useState<{ name: string; progress: number } | null>(null);
  const [panelTab, setPanelTab] = useState<PanelTab>("kick");
  const [kickUser, setKickUser] = useState(""); // streamer cuyos videos se ven en el panel de Kick
  const [ytChannel, setYtChannel] = useState(""); // canal cuyos videos se ven en el panel de YouTube
  const [pickedThumb, setPickedThumb] = useState<{ url: string; src: string } | null>(null); // miniatura del VOD elegido en el panel
  const formRef = useRef<HTMLFormElement>(null);

  const src = parseSource(url);
  const isKick = src?.type === "kick";
  useEffect(() => {
    const t = setTimeout(() => setChecked(isKick ? url.trim() : ""), 500);
    return () => clearTimeout(t);
  }, [url, isKick]);
  const info = useSourceInfo(checked, isKick && src?.kind !== "clip" && checked === url.trim());
  const vod = info.data?.type === "kick" && info.data.kind === "video" ? info.data : null;
  const range = checkRange(parseClock(from), parseClock(to), { from, to }, vod);
  // Kick: hace falta un VOD que exista y un tramo válido (un canal o un clip no se pueden crear).
  const blocked = isKick && (src?.kind !== "video" || !!range.problem || !!vod?.live || (info.isError && checked === url.trim()));

  /** Un enlace de canal (de Kick o de YouTube) no se crea: abre sus videos en el panel. */
  function openChannel(raw: string): boolean {
    const p = parseSource(raw);
    if (p?.kind !== "channel" || !p.id) return false;
    if (p.type === "kick") setKickUser(p.id);
    else setYtChannel(p.id);
    setPanelTab(p.type);
    setUrl("");
    return true;
  }

  /** Un video elegido en el panel de Kick pasa al formulario, donde se escoge el tramo. */
  function pickVod(vodUrl: string, thumbnail: string | null) {
    setUrl(vodUrl);
    setPickedThumb(thumbnail ? { url: vodUrl, src: thumbnail } : null);
    setFrom("");
    setTo("");
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  /** Un video elegido en el panel de YouTube pasa al formulario (se baja entero: no hay tramo). */
  function pickVideo(videoUrl: string) {
    setUrl(videoUrl);
    setPickedThumb(null);
    setFrom("");
    setTo("");
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function fromUrl(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim() || blocked || openChannel(url)) return;
    setBusy(true);
    try {
      const p = await api<ProjectDTO>("/api/projects", {
        method: "POST",
        json: { url, query, templateId, ...(isKick && range.end != null ? { start: range.start ?? 0, end: range.end } : {}) },
      });
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
        json: { sourceType: "upload", fileName: file.name, query, templateId },
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
        "relative grid gap-10 rounded-3xl transition-shadow lg:grid-cols-[minmax(0,1fr)_minmax(390px,450px)] lg:items-start lg:gap-14",
        dragging && "ring-2 ring-primary ring-offset-[14px] ring-offset-background",
      )}
    >
      <div className="min-w-0 lg:pt-4">
        <h1 className="max-w-[15ch] text-[clamp(2.6rem,5.4vw,4.75rem)] leading-[0.96] font-semibold tracking-[-0.03em] text-balance">
          Del stream de cinco horas al clip que todos comparten
        </h1>
        <p className="mt-5 max-w-[54ch] text-[17px] leading-relaxed text-muted-foreground">
          Pega un enlace de YouTube o de Kick, o suelta un archivo, y ClipAI hace el resto: caza los momentos con más gancho,
          le deja a cada uno el tiempo que su historia necesita (de {timecode(health?.clipMinSec ?? 60)} a {timecode(health?.clipMaxSec ?? 150)}),
          lo pone en vertical 9:16 y le añade subtítulos.
        </p>

        <form ref={formRef} onSubmit={fromUrl} className="mt-8 max-w-2xl">
          <InputWrapper className="h-16 gap-3 pr-2 pl-6 shadow-[0_18px_40px_-24px_rgb(0_0_0/0.9)]">
            <Link2 aria-hidden className="size-5 shrink-0 text-muted-foreground" />
            <InputControl
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onPaste={(e) => {
                const pasted = e.clipboardData.getData("text");
                if (openChannel(pasted)) e.preventDefault();
              }}
              placeholder="youtube.com/watch?v=… o kick.com/canal/videos/…"
              aria-label="Enlace de YouTube o de Kick"
              disabled={busy}
              className="text-base"
              autoFocus
            />
            <Button type="submit" size="lg" className="h-12 shrink-0 px-6 font-semibold" disabled={busy || !url.trim() || blocked}>
              {busy && !upload ? <Loader2 className="animate-spin" /> : <Scissors />} <span className="max-[430px]:sr-only">Crear clips</span>
            </Button>
          </InputWrapper>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" onClick={() => fileRef.current?.click()} disabled={busy}>
              <Upload /> Subir archivo MP4 o MOV
            </Button>
            <Button type="button" variant="outline" onClick={() => setShowQuery((v) => !v)} aria-expanded={showQuery}>
              <Search /> Buscar un momento concreto
            </Button>
            <Button asChild variant="outline">
              <Link href="/tendencias"><TrendingUp /> Ver qué está en tendencia</Link>
            </Button>
            {templates && templates.length > 0 && (
              <Select value={template} onValueChange={setTemplate} disabled={busy}>
                <SelectTrigger
                  className="max-w-full gap-2"
                  aria-label="Estilo de subtítulos del proyecto"
                  title="Automático: cada proyecto usa un estilo distinto al de los últimos. Todos sus clips salen con el mismo; en el estudio puedes cambiar el de cada uno."
                >
                  <Captions className="size-4" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO}>Subtítulos: automáticos</SelectItem>
                  {templates.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      Subtítulos: <span style={{ ...cssFont(t.font), color: t.highlight }}>{t.name}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
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
            <div className="mt-4">
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Por ejemplo: el momento donde habla de dinero"
                aria-label="Momento a buscar"
                maxLength={200}
              />
              <p className="mt-1.5 text-xs text-muted-foreground">Los clips que cumplen esta descripción aparecen primero.</p>
            </div>
          )}
        </form>

        {isKick && src && src.kind !== "channel" && (
          <SourcePreview kind={src.kind} query={info} from={from} to={to} onFrom={setFrom} onTo={setTo} range={range}
            thumbnail={pickedThumb?.url === url.trim() ? pickedThumb.src : null} />
        )}

        {upload && (
          <div className="mt-6 flex max-w-2xl items-center gap-3 text-sm">
            <FileVideo className="size-4 shrink-0 text-primary" />
            <span className="truncate">{upload.name}</span>
            <Progress value={upload.progress * 100} aria-label="Subida del archivo" className="flex-1" />
            <span className="tabular w-10 text-right text-muted-foreground">{Math.round(upload.progress * 100)}%</span>
          </div>
        )}
      </div>

      <SourcePanel
        tab={panelTab}
        onTab={setPanelTab}
        kickUser={kickUser}
        onKickUser={setKickUser}
        ytChannel={ytChannel}
        onYtChannel={setYtChannel}
        kickSelectedId={src?.type === "kick" && src.kind === "video" ? src.id : null}
        ytSelectedId={src?.type === "youtube" && src.kind === "video" ? src.id : null}
        onPickKick={pickVod}
        onPickYoutube={pickVideo}
      />

      {dragging && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center rounded-3xl bg-background/80 text-xl font-semibold text-primary">
          Suelta el video para empezar
        </div>
      )}
    </section>
  );
}
