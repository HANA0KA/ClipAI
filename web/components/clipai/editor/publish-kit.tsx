"use client";

import { Check, Copy, UploadCloud } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useNetworkTags, usePublishText } from "@/lib/client";
import { HOOK_MAX_CHARS } from "@/lib/hook";
import { cleanTags, composeNetwork, NETWORK_TAG_CAP, type TagNetwork } from "@/lib/network-tags";
import type { ClipDTO, Health } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CopyButton, useCopy } from "../copy-field";
import { SaveClipMenu } from "../save-clip";

interface Props {
  clip: ClipDTO;
  /** El gancho con su emoji: es el título, la descripción y el texto de la portada a la vez. */
  hook: string;
  hashtags: string;
  onChange: (field: "hook" | "hashtags", value: string) => void;
  health: Health | undefined;
  onPosted: (posted: boolean) => void;
  onUploadPost: () => void;
}

function Field({ id, label, count, max, children, copyText, action }: {
  id: string; label: string; count?: number; max?: number; children: React.ReactNode; copyText: string;
  action?: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id} className="text-xs text-muted-foreground">
          {label}
          {max ? (
            <span className={cn("tabular ml-2", (count ?? 0) > max ? "text-destructive" : "")}>
              {count}/{max}
            </span>
          ) : null}
        </Label>
        <div className="flex items-center gap-1">
          {action}
          <CopyButton text={copyText} label={label.toLowerCase()} id={id} />
        </div>
      </div>
      {children}
    </div>
  );
}

const NETWORKS: { id: TagNetwork; label: string; hint: string }[] = [
  { id: "youtube", label: "YouTube", hint: "#Shorts va siempre primero; YouTube muestra los tres primeros sobre el título e ignora todos si hay más de 15." },
  { id: "instagram", label: "Instagram", hint: "Instagram admite como máximo 5 por publicación." },
];

/** Fijas de una red (se editan aquí y valen para todos los videos) y cómo queda el juego final de este clip. */
function NetworkTagsField({ network, clipSet, pinned, onSave }: {
  network: (typeof NETWORKS)[number]; clipSet: string[] | undefined; pinned: string[]; onSave: (text: string) => void;
}) {
  const [text, setText] = useState(pinned.join(" "));
  const saved = pinned.join(" ");
  const live = cleanTags(text);
  const final = composeNetwork(network.id, clipSet, live);
  const commit = () => {
    if (live.join(" ") !== saved) onSave(text);
  };
  return (
    <Field id={`kit-${network.id}-tags`} label={`Hashtags de ${network.label}`} copyText={final.join(" ")}>
      <Input id={`kit-${network.id}-tags`} value={text} placeholder="#Clips #Podcast" className="mt-1"
        onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
      <p className="mt-1 text-xs text-muted-foreground">
        Tuyos, para todos los videos ({live.length}/{NETWORK_TAG_CAP[network.id]}). {network.hint}
      </p>
      <p className="mt-1 rounded-[var(--r-md)] bg-card px-3 py-2 text-sm break-words">{final.join(" ") || "—"}</p>
    </Field>
  );
}

const STATUS_TEXT: Record<string, string> = {
  QUEUED: "Envío en cola",
  RUNNING: "Enviando…",
  DONE: "Publicado",
  SCHEDULED: "Tope diario alcanzado: se enviará mañana",
  FAILED: "El envío falló",
  KIT: "Kit listo",
};

export function PublishKit(p: Props) {
  const { copied, copy } = useCopy();
  const rendered = p.clip.renderStatus === "DONE";
  const { data: post } = usePublishText(p.clip.id, p.hook, p.hashtags);
  const { tags: netTags, save: saveNetTags } = useNetworkTags();
  const title = post?.title ?? p.hook;
  const description = post?.description ?? p.hook;
  const tags = post?.hashtags ?? p.hashtags;
  const all = [title, description, tags].filter(Boolean).join("\n\n");
  const uploadPost = p.health?.publishers?.find((x) => x.name === "upload_post");
  const busy = p.clip.publishStatus === "QUEUED" || p.clip.publishStatus === "RUNNING";

  return (
    <div className="space-y-4">
      <Field id="kit-hook" label="Gancho (portada, video y nombre de los archivos)" count={p.hook.length} max={HOOK_MAX_CHARS} copyText={p.hook}>
        <Input id="kit-hook" value={p.hook} maxLength={120} onChange={(e) => p.onChange("hook", e.target.value)} className="mt-1" />
        <p className="mt-1 text-xs text-muted-foreground">
          Es el texto de la portada y del video, y el nombre de los archivos. Termina con un emoji: se ve a color en la
          portada y encima del gancho en el video. Al publicar se le suma el creador (abajo).
        </p>
      </Field>

      <section aria-label="Lo que se publica" className="space-y-3 rounded-[var(--r-card-sm)] bg-secondary/60 p-4">
        <p className="text-xs text-muted-foreground">
          Así se publica{post?.creator ? <> (creador: <span className="font-medium text-foreground">{post.creator}</span>)</> : " (el video no trae creador)"}.
          YouTube y su buscador leen el nombre en el título, en las primeras líneas de la descripción y en los hashtags.
        </p>
        <Field id="kit-title" label="Título para publicar" count={title.length} max={100} copyText={title}>
          <p id="kit-title" className="mt-1 rounded-[var(--r-md)] bg-card px-3 py-2 text-sm">{title || "—"}</p>
        </Field>
        <Field id="kit-desc" label="Descripción" copyText={description}>
          <p id="kit-desc" className="mt-1 rounded-[var(--r-md)] bg-card px-3 py-2 text-sm break-words whitespace-pre-wrap">{description || "—"}</p>
        </Field>
        {NETWORKS.map((n) => (
          <NetworkTagsField key={`${n.id}:${(netTags?.[n.id] ?? []).join(" ")}`} network={n} clipSet={p.clip.hashtagSets?.[n.id]} pinned={netTags?.[n.id] ?? []}
            onSave={(text) => saveNetTags.mutate({ [n.id]: text }, {
              onSuccess: () => toast.success(`Hashtags de ${n.label} guardados para todos los videos`),
              onError: (e) => toast.error((e as Error).message),
            })} />
        ))}
        <Field id="kit-final-tags" label="Hashtags para publicar" copyText={tags}>
          <p id="kit-final-tags" className="mt-1 rounded-[var(--r-md)] bg-card px-3 py-2 text-sm break-words">{tags || "—"}</p>
        </Field>
      </section>
      <Field id="kit-tags" label="Hashtags del clip (editables)" copyText={p.hashtags}>
        <Input id="kit-tags" value={p.hashtags} onChange={(e) => p.onChange("hashtags", e.target.value)} className="mt-1" />
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => copy("all", all)}>
          {copied === "all" ? <Check className="text-success" /> : <Copy />} Copiar todo
        </Button>
        <SaveClipMenu clip={p.clip} label="Descargar" />
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

      {uploadPost?.available && (
        <div className="space-y-2 border-t border-border pt-4">
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
