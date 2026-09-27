"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Loader2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, useClip, useHealth, useTemplates } from "@/lib/client";
import { timecode } from "@/lib/format";
import type { ClipDetail, LayoutMode } from "@/lib/types";
import { BoundsEditor } from "./editor/bounds-editor";
import { CaptionEditor } from "./editor/caption-editor";
import { LayoutPicker } from "./editor/layout-picker";
import { PublishKit } from "./editor/publish-kit";
import { TemplatePicker } from "./editor/template-picker";
import { type PlayerHandle, VerticalPlayer } from "./editor/vertical-player";
import { WhyPanel } from "./editor/why-panel";

interface Form {
  startSec: number;
  endSec: number;
  hook: string;
  title: string;
  description: string;
  hashtags: string;
  templateId: string;
  smartCut: boolean;
  prependBestLine: boolean;
}

function formFrom(d: ClipDetail): Form {
  const c = d.clip;
  return {
    startSec: c.startSec, endSec: c.endSec, hook: c.hook, title: c.title, description: c.description,
    hashtags: c.hashtags, templateId: c.templateId, smartCut: c.smartCut, prependBestLine: c.prependBestLine,
  };
}

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="border-t border-border py-5 first:border-t-0 first:pt-0">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="font-condensed text-lg font-bold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function ClipEditor({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useClip(id);
  const { data: templates } = useTemplates();
  const { data: health } = useHealth();
  const player = useRef<PlayerHandle>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [view, setView] = useState<"final" | "original">("final");
  const loadedFor = useRef<string | null>(null);

  // Inicializa el formulario una vez por clip (no pisa lo que estás editando
  // cuando el sondeo trae el estado del render).
  useEffect(() => {
    if (data && loadedFor.current !== data.clip.id) {
      loadedFor.current = data.clip.id;
      setForm(formFrom(data));
      setView(data.clip.renderStatus === "DONE" ? "final" : "original");
    }
  }, [data]);

  const dirtyFields = useMemo(() => {
    if (!data || !form) return {};
    const base = formFrom(data);
    return Object.fromEntries(
      (Object.keys(form) as (keyof Form)[]).filter((k) => form[k] !== base[k]).map((k) => [k, form[k]]),
    ) as Partial<Form>;
  }, [data, form]);
  const dirty = Object.keys(dirtyFields).length > 0 || Object.keys(edits).length > 0;

  if (isLoading || !form) {
    return (
      <div className="grid gap-8 pt-8 lg:grid-cols-[340px_1fr_360px]">
        <Skeleton className="aspect-[9/16]" />
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <p className="pt-10 text-destructive">{(error as Error)?.message ?? "Clip no encontrado"}</p>
    );
  }

  const { clip, project, captions } = data;
  const busy = clip.renderStatus === "QUEUED" || clip.renderStatus === "RUNNING";
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));

  async function save(): Promise<boolean> {
    if (!dirty) return true;
    try {
      const words = Object.entries(edits).map(([i, w]) => ({ i: Number(i), w }));
      const fresh = await api<ClipDetail>(`/api/clips/${id}`, {
        method: "PATCH",
        json: { ...dirtyFields, ...(words.length ? { words } : {}) },
      });
      qc.setQueryData(["clip", id], fresh);
      loadedFor.current = fresh.clip.id;
      setForm(formFrom(fresh));
      setEdits({});
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  }

  async function saveAndRender() {
    setSaving(true);
    if (await save()) {
      try {
        await api(`/api/clips/${id}/render`, { method: "POST" });
        toast.success("Cambios guardados; renderizando el clip");
        qc.invalidateQueries({ queryKey: ["clip", id] });
      } catch (e) {
        toast.error((e as Error).message);
      }
    }
    setSaving(false);
  }

  async function changeLayout(mode: LayoutMode) {
    setSaving(true);
    if (await save()) {
      try {
        await api(`/api/clips/${id}/reframe`, { method: "POST", json: { mode } });
        toast.success("Diseño cambiado; re-renderizando desde el trozo original");
        qc.invalidateQueries({ queryKey: ["clip", id] });
      } catch (e) {
        toast.error((e as Error).message);
      }
    }
    setSaving(false);
  }

  async function quickPatch(body: Record<string, unknown>) {
    try {
      qc.setQueryData(["clip", id], await api<ClipDetail>(`/api/clips/${id}`, { method: "PATCH", json: body }));
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function sendJob(path: string, body: unknown, ok: string) {
    try {
      await api(path, { method: "POST", json: body });
      toast.success(ok);
      qc.invalidateQueries({ queryKey: ["clip", id] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const canEditBounds = !project.sourceDeleted;
  const hookWords = form.hook.trim().split(/\s+/).filter(Boolean).length;

  return (
    <div className="pt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href={`/projects/${project.id}`}
          className="inline-flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4 shrink-0" />
          <span className="truncate">{project.title}</span>
        </Link>
        <div className="flex items-center gap-3">
          {dirty && <span className="text-xs text-primary">Cambios sin renderizar</span>}
          {dirty && (
            <Button variant="ghost" size="sm" onClick={() => { setForm(formFrom(data)); setEdits({}); }}>
              <RotateCcw /> Descartar cambios
            </Button>
          )}
          <Button onClick={saveAndRender} disabled={saving || busy}>
            {saving || busy ? <Loader2 className="animate-spin" /> : null}
            {busy ? (clip.renderStatus === "RUNNING" ? "Renderizando…" : "En cola…") : "Guardar y renderizar"}
          </Button>
        </div>
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(260px,340px)_1fr] xl:grid-cols-[minmax(260px,340px)_1fr_360px]">
        {/* Visor */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <Tabs value={view} onValueChange={(v) => setView(v as "final" | "original")} className="mb-3">
            <TabsList className="w-full">
              <TabsTrigger value="final" className="flex-1">Clip final</TabsTrigger>
              <TabsTrigger value="original" className="flex-1">Fragmento original</TabsTrigger>
            </TabsList>
          </Tabs>
          <VerticalPlayer
            ref={player}
            mode={view}
            finalUrl={clip.videoUrl}
            posterUrl={clip.thumbUrl}
            sourceUrl={project.sourceVideoUrl}
            start={form.startSec}
            end={form.endSec}
          />
          <p className="tabular mt-2 text-center text-xs text-muted-foreground">
            {timecode(form.startSec, true)} a {timecode(form.endSec, true)}
          </p>
          {clip.renderStatus === "FAILED" && (
            <p className="mt-3 flex gap-2 text-xs text-destructive">
              <AlertTriangle className="size-4 shrink-0" /> {clip.renderError}
            </p>
          )}
          {clip.qaWarnings.length > 0 && clip.renderStatus === "DONE" && (
            <ul className="mt-3 space-y-1 text-xs text-primary">
              {clip.qaWarnings.map((w) => (
                <li key={w} className="flex gap-2">
                  <AlertTriangle className="size-3.5 shrink-0" /> {w}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Contenido */}
        <div className="min-w-0">
          <Section title="Bordes" aside={!canEditBounds ? <span className="text-xs text-muted-foreground">Fuente borrada: bordes fijos</span> : null}>
            <BoundsEditor
              start={form.startSec}
              end={form.endSec}
              videoDuration={project.durationSec ?? 0}
              disabled={!canEditBounds}
              onChange={(s, e) => setForm((f) => (f ? { ...f, startSec: s, endSec: e } : f))}
            />
            {clip.bestLineStart != null && (
              <div className="mt-4 flex items-start gap-3 rounded-lg bg-card p-3">
                <Switch
                  id="prepend"
                  checked={form.prependBestLine}
                  onCheckedChange={(v) => set("prependBestLine", v)}
                  disabled={!canEditBounds}
                />
                <Label htmlFor="prepend" className="block text-sm leading-snug font-normal">
                  Abrir con la frase más fuerte
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    Antepone {((clip.bestLineEnd ?? 0) - clip.bestLineStart).toFixed(1)} s de «{clip.bestLine}» al
                    inicio, como avance.
                  </span>
                </Label>
              </div>
            )}
          </Section>

          <Section
            title="Palabras"
            aside={
              <span className="text-xs text-muted-foreground">
                {captions.source === "whisper" ? "Pulidas con Whisper" : "De los subtítulos"}. Doble clic para corregir.
              </span>
            }
          >
            <CaptionEditor
              words={captions.words}
              start={form.startSec}
              end={form.endSec}
              edits={edits}
              onEdit={(i, w) => setEdits((e) => ({ ...e, [i]: w }))}
              onSeek={(t) => {
                setView("original");
                setTimeout(() => player.current?.seek(t), 50);
              }}
            />
          </Section>

          <Section title="Gancho en pantalla" aside={<span className="tabular text-xs text-muted-foreground">{hookWords} palabras</span>}>
            <Input value={form.hook} maxLength={120} onChange={(e) => set("hook", e.target.value)} aria-label="Texto del gancho" />
            <p className="mt-1.5 text-xs text-muted-foreground">Arriba del video durante los primeros 3 s. Mejor con 8 palabras o menos.</p>
          </Section>

          <Section title="Plantilla de subtítulos">
            {templates ? <TemplatePicker templates={templates} value={form.templateId} onChange={(v) => set("templateId", v)} /> : <Skeleton className="h-24" />}
            <div className="mt-4 flex items-start gap-3">
              <Switch id="smartcut" checked={form.smartCut} onCheckedChange={(v) => set("smartCut", v)} />
              <Label htmlFor="smartcut" className="block text-sm leading-snug font-normal">
                Corte inteligente
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  Quita silencios largos y muletillas. Puede comerse una pausa dramática.
                </span>
              </Label>
            </div>
          </Section>

          <Section title="Encuadre" aside={<span className="text-xs text-muted-foreground">Cambiarlo re-renderiza el clip</span>}>
            <LayoutPicker value={clip.layoutMode} onChange={changeLayout} disabled={saving || busy} />
          </Section>
        </div>

        {/* Kit y razones */}
        <div className="min-w-0 lg:col-span-2 xl:col-span-1">
          <Section title="Kit de publicación">
            <PublishKit
              clip={clip}
              title={form.title}
              description={form.description}
              hashtags={form.hashtags}
              onChange={(k, v) => set(k, v)}
              health={health}
              onPosted={(posted) => quickPatch({ posted })}
              onTikTok={async () => {
                if (await save()) sendJob(`/api/clips/${id}/tiktok`, {}, "Enviando a tus borradores de TikTok");
              }}
              onUploadPost={async () => {
                if (await save()) sendJob(`/api/clips/${id}/publish`, { platforms: ["youtube"] }, "Publicación en cola");
              }}
            />
          </Section>
          <Section title="Por qué este clip">
            <WhyPanel clip={clip} />
          </Section>
        </div>
      </div>
    </div>
  );
}
