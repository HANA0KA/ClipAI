"use client";

import { Check, Copy, Download, Send, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ClipDTO, Health } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CopyButton, useCopy } from "../copy-field";

interface Props {
  clip: ClipDTO;
  title: string;
  description: string;
  hashtags: string;
  onChange: (field: "title" | "description" | "hashtags", value: string) => void;
  health: Health | undefined;
  onPosted: (posted: boolean) => void;
  onTikTok: () => void;
  onUploadPost: () => void;
}

function Field({ id, label, count, max, children, copyText }: {
  id: string; label: string; count?: number; max?: number; children: React.ReactNode; copyText: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <Label htmlFor={id} className="text-xs text-muted-foreground">
          {label}
          {max ? (
            <span className={cn("tabular ml-2", (count ?? 0) > max ? "text-destructive" : "")}>
              {count}/{max}
            </span>
          ) : null}
        </Label>
        <CopyButton text={copyText} label={label.toLowerCase()} id={id} />
      </div>
      {children}
    </div>
  );
}

const STATUS_TEXT: Record<string, string> = {
  QUEUED: "Envío en cola",
  RUNNING: "Enviando…",
  DRAFT: "En tus borradores de TikTok: abre la notificación en la app para terminar",
  DONE: "Publicado",
  SCHEDULED: "Tope diario alcanzado: se enviará mañana",
  FAILED: "El envío falló",
  KIT: "Kit listo",
};

export function PublishKit(p: Props) {
  const { copied, copy } = useCopy();
  const rendered = p.clip.renderStatus === "DONE";
  const all = [p.title, p.description, p.hashtags].filter(Boolean).join("\n\n");
  const tiktok = p.health?.publishers?.find((x) => x.name === "tiktok_draft");
  const uploadPost = p.health?.publishers?.find((x) => x.name === "upload_post");
  const busy = p.clip.publishStatus === "QUEUED" || p.clip.publishStatus === "RUNNING";

  return (
    <div className="space-y-4">
      <Field id="kit-title" label="Título" count={p.title.length} max={100} copyText={p.title}>
        <Input id="kit-title" value={p.title} onChange={(e) => p.onChange("title", e.target.value)} className="mt-1" />
      </Field>
      <Field id="kit-desc" label="Descripción" copyText={p.description}>
        <Textarea id="kit-desc" value={p.description} rows={3} onChange={(e) => p.onChange("description", e.target.value)} className="mt-1" />
      </Field>
      <Field id="kit-tags" label="Hashtags" copyText={p.hashtags}>
        <Input id="kit-tags" value={p.hashtags} onChange={(e) => p.onChange("hashtags", e.target.value)} className="mt-1" />
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => copy("all", all)}>
          {copied === "all" ? <Check className="text-success" /> : <Copy />} Copiar todo
        </Button>
        {rendered && p.clip.downloadUrl ? (
          <Button asChild size="sm">
            <a href={p.clip.downloadUrl} download>
              <Download /> Descargar MP4
            </a>
          </Button>
        ) : (
          <Button size="sm" disabled>
            <Download /> Descargar MP4
          </Button>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={!!p.clip.postedAt} onCheckedChange={(v) => p.onPosted(v === true)} />
        Ya lo subí
        {p.clip.postedAt && (
          <span className="text-xs text-muted-foreground">
            ({new Date(p.clip.postedAt).toLocaleDateString("es", { day: "numeric", month: "short" })})
          </span>
        )}
      </label>

      {(tiktok?.available || uploadPost?.available) && (
        <div className="space-y-2 border-t border-border pt-4">
          {tiktok?.available &&
            (tiktok.connected ? (
              <Button type="button" variant="outline" size="sm" className="w-full" disabled={!rendered || busy} onClick={p.onTikTok}>
                <Send /> Enviar a borradores de TikTok
              </Button>
            ) : (
              <Button asChild variant="outline" size="sm" className="w-full">
                <a href="/api/tiktok/connect">Conectar TikTok (una sola vez)</a>
              </Button>
            ))}
          {uploadPost?.available && (
            <Button type="button" variant="outline" size="sm" className="w-full" disabled={!rendered || busy} onClick={p.onUploadPost}>
              <UploadCloud /> Publicar en YouTube con Upload-Post
            </Button>
          )}
        </div>
      )}
      {p.clip.publishStatus && (
        <p className={cn("text-xs", p.clip.publishStatus === "FAILED" ? "text-destructive" : "text-muted-foreground")}>
          {STATUS_TEXT[p.clip.publishStatus] ?? p.clip.publishStatus}
          {p.clip.publishInfo?.error ? `: ${p.clip.publishInfo.error}` : ""}
          {p.clip.publishInfo?.url ? (
            <>
              {" "}
              <a href={p.clip.publishInfo.url} target="_blank" rel="noreferrer" className="underline">
                Ver publicación
              </a>
            </>
          ) : null}
        </p>
      )}
    </div>
  );
}
