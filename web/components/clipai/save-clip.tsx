"use client";

import { Download, FolderDown, Image as ImageIcon, Loader2, Video } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { canSaveAs, saveClipToFolder, saveFileAs } from "@/lib/export-folder";
import type { ClipDTO } from "@/lib/types";

/**
 * Descargar un clip eligiendo dónde guardarlo: video y portada juntos en una
 * carpeta, o solo uno de los dos con «Guardar como…» (nombre y lugar a tu
 * gusto). El nombre propuesto es el gancho, con el número de publicación.
 */
export function SaveClipMenu({ clip, label, size = "sm" }: { clip: ClipDTO; label?: string; size?: "sm" | "icon-sm" }) {
  const [busy, setBusy] = useState(false);
  const ready = clip.renderStatus === "DONE" && !!clip.downloadUrl;

  async function run(job: () => Promise<string | boolean | null>, done: (r: string | true) => string) {
    setBusy(true);
    try {
      const r = await job();
      if (r) toast.success(done(r === true ? true : String(r)));
    } catch (e) {
      toast.error(`No se pudo guardar: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={label ? "default" : "outline"} size={size} disabled={!ready || busy} aria-label="Descargar"
          title={ready ? "Descargar eligiendo dónde guardarlo" : "Renderiza el clip primero"}>
          {busy ? <Loader2 className="animate-spin" /> : <Download />}
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {canSaveAs() ? "Tú eliges dónde se guarda" : "Se descarga a Descargas (Chrome o Edge dejan elegir)"}
        </DropdownMenuLabel>
        <DropdownMenuItem disabled={!clip.downloadUrl} onSelect={() => void run(() => saveClipToFolder(clip),
          (r) => `Video${clip.coverDownloadUrl ? " y portada" : ""} guardados en «${r}»`)}>
          <FolderDown /> {clip.coverDownloadUrl ? "Video y portada en una carpeta…" : "Video en una carpeta…"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void run(() => saveFileAs(clip.downloadUrl!, `${clip.fileBase}.mp4`, "video"),
          () => "Video guardado")}>
          <Video /> Solo el video…
        </DropdownMenuItem>
        <DropdownMenuItem disabled={!clip.coverDownloadUrl}
          onSelect={() => void run(() => saveFileAs(clip.coverDownloadUrl!, `${clip.fileBase} - portada.jpg`, "image"),
            () => "Portada guardada")}>
          <ImageIcon /> Solo la portada…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
