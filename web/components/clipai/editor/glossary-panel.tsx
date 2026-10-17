"use client";

import { BookMarked, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useGlossary } from "@/lib/client";
import { coreText, MAX_TEXT } from "@/lib/glossary";

/**
 * Glosario de correcciones: lo que siempre se transcribe mal. Cada regla se
 * aplica a este clip (en el borrador, se puede deshacer), a los subtítulos de
 * los demás clips y a todos los clips que se creen después.
 */
export function GlossaryPanel({ onAdd, onRemove }: {
  onAdd: (from: string, to: string) => Promise<void>;
  onRemove: (from: string) => Promise<void>;
}) {
  const { data: rules = [] } = useGlossary();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const a = coreText(from);
  const b = coreText(to);
  const ready = !!a && !!b && a !== b;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    try {
      await onAdd(a, b);
      setFrom("");
      setTo("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="group mt-4 rounded-lg border border-border bg-well/40 px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium select-none">
        <BookMarked className="size-4 text-primary" /> Glosario de correcciones
        <span className="tabular text-xs font-normal text-muted-foreground">({rules.length})</span>
        <span className="ml-auto text-xs font-normal text-muted-foreground group-open:hidden">Mostrar</span>
      </summary>
      <p className="mt-2 text-xs text-muted-foreground">
        Palabras que siempre se transcriben mal. Al añadir una regla se corrige en este clip, en los demás clips y en
        todos los que crees después. Sin importar mayúsculas; los acentos sí cuentan. Puede ser una frase («cloud code»).
      </p>
      <form onSubmit={submit} className="mt-3 flex flex-wrap items-center gap-2">
        <Input value={from} onChange={(e) => setFrom(e.target.value)} maxLength={MAX_TEXT} placeholder="Se transcribe como…"
          aria-label="Como se transcribe mal" className="h-8 w-48" />
        <span aria-hidden className="text-muted-foreground">→</span>
        <Input value={to} onChange={(e) => setTo(e.target.value)} maxLength={MAX_TEXT} placeholder="Debe decir…"
          aria-label="Como debe decir" className="h-8 w-48" />
        <Button type="submit" size="sm" variant="secondary" disabled={!ready || busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Plus />} Añadir y aplicar
        </Button>
      </form>
      {rules.length > 0 && (
        <ul className="mt-3 max-h-56 space-y-1 overflow-y-auto pr-1 text-sm">
          {rules.map((r) => (
            <li key={r.from} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-accent/50">
              <span className="text-muted-foreground line-through decoration-destructive/60">{r.from}</span>
              <span aria-hidden>→</span>
              <span className="font-medium">{r.to}</span>
              <Button type="button" variant="ghost" size="icon-sm" className="ml-auto size-6" aria-label={`Quitar la regla ${r.from}`}
                title="Quitar la regla (no deshace lo ya corregido)" onClick={() => void onRemove(r.from)}>
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
