"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, useFonts } from "@/lib/client";
import type { FontInfo } from "@/lib/types";
import { cssFont } from "./template-picker";

const TEMPLATE = "__plantilla__";

/** Carga las fuentes subidas en el navegador para previsualizarlas. */
function useLoadFonts(fonts: FontInfo[] | undefined) {
  useEffect(() => {
    for (const f of fonts ?? []) {
      if (f.builtin || !f.url || typeof FontFace === "undefined") continue;
      const already = [...document.fonts].some((ff) => ff.family.replace(/"/g, "") === f.name);
      if (already) continue;
      new FontFace(f.name, `url(${f.url})`).load().then((ff) => document.fonts.add(ff)).catch(() => {});
    }
  }, [fonts]);
}

/** Fuente de subtítulos y gancho: la de la plantilla o una elegida (o subida). */
export function FontPicker({ value, onChange }: { value: string | null; onChange: (font: string | null) => void }) {
  const qc = useQueryClient();
  const { data: fonts } = useFonts();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  useLoadFonts(fonts);
  const names = [...new Map((fonts ?? []).map((f) => [f.name, f])).values()];
  const current = value ?? TEMPLATE;
  const userFont = (fonts ?? []).find((f) => !f.builtin && f.name === value);

  async function upload(file: File) {
    setBusy(true);
    try {
      const font = await api<FontInfo>(`/api/fonts?name=${encodeURIComponent(file.name)}`, {
        method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" },
      });
      await qc.invalidateQueries({ queryKey: ["fonts"] });
      onChange(font.name);
      toast.success(`Fuente «${font.name}» lista`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove(f: FontInfo) {
    try {
      await api(`/api/fonts/${encodeURIComponent(f.file)}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["fonts"] });
      if (value === f.name) onChange(null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={current} onValueChange={(v) => onChange(v === TEMPLATE ? null : v)}>
        <SelectTrigger className="w-56" aria-label="Fuente de los subtítulos">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={TEMPLATE}>La de la plantilla</SelectItem>
          {names.map((f) => (
            <SelectItem key={f.name} value={f.name}>
              <span style={cssFont(f.name)}>{f.name}</span>
              {!f.builtin && <span className="ml-1 text-xs text-muted-foreground">(subida)</span>}
            </SelectItem>
          ))}
          {value && !names.some((f) => f.name === value) && <SelectItem value={value}>{value} (no encontrada)</SelectItem>}
        </SelectContent>
      </Select>
      <input
        ref={input}
        type="file"
        accept=".ttf,.otf,font/ttf,font/otf"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />
      <Button variant="secondary" size="sm" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Loader2 className="animate-spin" /> : <Upload />} Subir fuente
      </Button>
      {userFont && (
        <Button variant="ghost" size="icon-sm" aria-label={`Borrar la fuente ${userFont.name}`} onClick={() => remove(userFont)}>
          <Trash2 />
        </Button>
      )}
    </div>
  );
}
