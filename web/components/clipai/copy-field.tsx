"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(key);
    setTimeout(() => setCopied((k) => (k === key ? null : k)), 1500);
  }
  return { copied, copy };
}

export function CopyButton({ text, label, id }: { text: string; label: string; id: string }) {
  const { copied, copy } = useCopy();
  const done = copied === id;
  return (
    <Button type="button" variant="ghost" size="icon-sm" aria-label={`Copiar ${label}`} onClick={() => copy(id, text)}>
      {done ? <Check className="text-success" /> : <Copy />}
    </Button>
  );
}
