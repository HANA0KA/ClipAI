"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, Flame, Loader2, MessageCircle, RefreshCw, Scissors, Search, ThumbsUp, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, trendingUrl, type TrendingParams, useTrending } from "@/lib/client";
import { duration as fmtDuration } from "@/lib/format";
import type { ProjectDTO, TrendingItem, TrendingResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIER: Record<TrendingItem["tier"], { label: string; badge: string }> = {
  "muy alto": { label: "Potencial muy alto", badge: "bg-success text-background" },
  alto: { label: "Potencial alto", badge: "bg-primary text-primary-foreground" },
  medio: { label: "Potencial medio", badge: "bg-secondary text-secondary-foreground" },
  bajo: { label: "Potencial bajo", badge: "bg-muted text-muted-foreground" },
};

const LANGS: Record<string, string> = { es: "Español", en: "Inglés", pt: "Portugués", fr: "Francés", it: "Italiano", de: "Alemán" };

const PART_LABEL: [keyof TrendingItem["parts"], string, number][] = [
  ["momentum", "Impulso", 35], ["outperform", "Rendimiento", 20], ["engagement", "Reacción", 15], ["clips", "Material para clips", 30],
];

/** 5 850 939 → «5,9 M»; 845 000 → «845 mil» (igual que media/services/trending.py). */
function count(n: number | null): string {
  if (n == null) return "–";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 100_000_000 ? 0 : 1).replace(/\.0$/, "").replace(".", ",")} M`;
  if (n >= 10_000) return `${Math.round(n / 1000)} mil`;
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(".", ",")} mil`;
  return String(n);
}

function age(days: number | null): string {
  if (days == null) return "";
  if (days < 1) return "hoy";
  const d = Math.round(days);
  return d === 1 ? "hace 1 día" : d < 60 ? `hace ${d} días` : `hace ${Math.round(d / 30)} meses`;
}

function Card({ item, onCreate, creating }: { item: TrendingItem; onCreate: (i: TrendingItem) => void; creating: boolean }) {
  const tier = TIER[item.tier];
  return (
    <li className="flex gap-4 rounded-xl border border-border bg-card p-3">
      <a href={item.url} target="_blank" rel="noreferrer" className="relative block aspect-video w-40 shrink-0 self-start overflow-hidden rounded-lg bg-well sm:w-52"
        aria-label={`Ver «${item.title}» en YouTube`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={item.thumbnail} alt="" className="size-full object-cover" loading="lazy" />
        <span className="tabular absolute right-1 bottom-1 rounded bg-black/75 px-1 text-[11px] text-white">{fmtDuration(item.durationSec)}</span>
      </a>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="line-clamp-2 leading-snug font-medium">{item.title}</p>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {item.channel} · {count(item.views)} vistas{item.ageDays != null ? ` · ${age(item.ageDays)}` : ""}
            </p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
              {item.likes != null && <span className="inline-flex items-center gap-1"><ThumbsUp className="size-3" />{count(item.likes)}</span>}
              {item.comments != null && <span className="inline-flex items-center gap-1"><MessageCircle className="size-3" />{count(item.comments)}</span>}
              {item.chapters > 0 && <span>{item.chapters} capítulos</span>}
            </p>
          </div>
          <div className="shrink-0 text-center" title={PART_LABEL.map(([k, name, max]) => `${name}: ${item.parts[k]}/${max}`).join("\n")}>
            <span className={cn("font-condensed tabular inline-flex min-w-11 items-center justify-center rounded-md px-1.5 text-2xl leading-8 font-extrabold", tier.badge)}
              aria-label={`Puntaje ${item.score} de 100`}>
              {item.score}
            </span>
            <span className="mt-0.5 block text-[10px] leading-tight text-muted-foreground">{tier.label}</span>
          </div>
        </div>
        <ul className="mt-2 space-y-0.5 text-xs">
          {item.reasons.slice(0, 4).map((r) => (
            <li key={r} className="flex gap-1.5"><Flame className="mt-0.5 size-3 shrink-0 text-primary" /><span>{r}</span></li>
          ))}
          {item.warnings.map((w) => (
            <li key={w} className="flex gap-1.5 text-muted-foreground"><AlertTriangle className="mt-0.5 size-3 shrink-0" /><span>{w}</span></li>
          ))}
        </ul>
        <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
          {item.project ? (
            <Button asChild size="sm" variant="secondary"><Link href={`/projects/${item.project}`}><Scissors /> Ya lo usas: ver proyecto</Link></Button>
          ) : (
            <Button size="sm" onClick={() => onCreate(item)} disabled={creating}>
              {creating ? <Loader2 className="animate-spin" /> : <Scissors />} Crear clips
            </Button>
          )}
          <Button asChild size="sm" variant="ghost">
            <a href={item.url} target="_blank" rel="noreferrer"><ExternalLink /> Ver en YouTube</a>
          </Button>
          {item.topics.length > 0 && <span className="ml-auto truncate text-[11px] text-muted-foreground">{item.topics.join(" · ")}</span>}
        </div>
      </div>
    </li>
  );
}

export function TrendingView() {
  const router = useRouter();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [params, setParams] = useState<TrendingParams>({ q: "", period: "week", sort: "views", duration: "long", lang: "auto" });
  const [refreshing, setRefreshing] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const { data, isLoading, isFetching, error, refetch } = useTrending(params);
  const busy = isLoading || (isFetching && !refreshing);

  function search(e?: FormEvent) {
    e?.preventDefault();
    setParams((p) => ({ ...p, q: text.trim() }));
  }
  function pick(topic: string) {
    setText(topic);
    setParams((p) => ({ ...p, q: topic }));
  }

  async function refresh() {
    setRefreshing(true);
    try {
      qc.setQueryData(["trending", params], await api<TrendingResponse>(trendingUrl(params, true)));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  async function create(item: TrendingItem) {
    setCreating(item.id);
    try {
      const p = await api<ProjectDTO>("/api/projects", { method: "POST", json: { url: item.url } });
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Proyecto creado: buscando los mejores momentos");
      router.push(`/projects/${p.id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setCreating(null);
    }
  }

  const meta = data?.meta;
  const hidden = meta ? Object.entries(meta.hidden).map(([why, n]) => `${n} ${why}`).join(", ") : "";
  return (
    <div className="pt-8">
      <header className="max-w-3xl">
        <h1 className="font-condensed flex items-center gap-2.5 text-4xl leading-tight font-extrabold sm:text-5xl">
          <TrendingUp className="size-9 text-primary" aria-hidden /> Tendencias
        </h1>
        <p className="mt-2 text-muted-foreground">
          Los videos más vistos de YouTube ahora mismo, puntuados por su potencial para clips: qué tan rápido crecen, si rinden
          más que su canal, cuánta reacción tienen y cuánto material hay (duración, capítulos, subtítulos).
        </p>
      </header>

      <form onSubmit={search} className="mt-6 flex max-w-3xl flex-col gap-2 sm:flex-row">
        <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={100} aria-label="Buscar un tema"
          placeholder={`Busca un tema… (vacío: ${data?.topics.slice(0, 4).join(", ") || "podcast, entrevista, debate"}…)`} className="h-10 flex-1" />
        <Button type="submit" className="h-10" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Search />} Buscar</Button>
      </form>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <ToggleGroup type="single" variant="pink" size="sm" value={params.period} aria-label="Periodo"
          onValueChange={(v) => v && setParams((p) => ({ ...p, period: v as TrendingParams["period"] }))}>
          {([["day", "Hoy"], ["week", "Esta semana"], ["month", "Este mes"]] as const).map(([v, l]) => (
            <ToggleGroupItem key={v} value={v}>{l}</ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Select value={params.duration} onValueChange={(v) => setParams((p) => ({ ...p, duration: v as TrendingParams["duration"] }))}>
          <SelectTrigger size="sm" aria-label="Duración" className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="long">Más de 20 min</SelectItem>
            <SelectItem value="medium">De 4 a 20 min</SelectItem>
            <SelectItem value="any">Cualquier duración</SelectItem>
          </SelectContent>
        </Select>
        <Select value={params.lang} onValueChange={(v) => setParams((p) => ({ ...p, lang: v }))}>
          <SelectTrigger size="sm" aria-label="Idioma hablado" className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">Mi idioma{data?.defaultLang ? ` (${LANGS[data.defaultLang] ?? data.defaultLang})` : ""}</SelectItem>
            {Object.entries(LANGS).map(([code, name]) => <SelectItem key={code} value={code}>{name}</SelectItem>)}
            <SelectItem value="any">Cualquier idioma</SelectItem>
          </SelectContent>
        </Select>
        <Select value={params.sort} onValueChange={(v) => setParams((p) => ({ ...p, sort: v as TrendingParams["sort"] }))}>
          <SelectTrigger size="sm" aria-label="Orden de la búsqueda" className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="views">Más vistos</SelectItem>
            <SelectItem value="date">Más recientes</SelectItem>
          </SelectContent>
        </Select>
        <Button size="sm" variant="ghost" onClick={refresh} disabled={refreshing || busy} title="Vuelve a consultar YouTube (si no, se reutiliza lo de hace menos de 30 min)">
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />} Actualizar
        </Button>
      </div>

      {(data?.topics.length ?? 0) > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Temas:</span>
          {data!.topics.map((t) => (
            <button key={t} type="button" onClick={() => pick(t)}
              className={cn("rounded-full border px-2.5 py-0.5 text-xs outline-none hover:border-primary hover:text-primary focus-visible:ring-2 focus-visible:ring-ring",
                params.q.toLowerCase() === t.toLowerCase() ? "border-primary text-primary" : "border-border text-muted-foreground")}>
              {t}
            </button>
          ))}
        </div>
      )}

      <section className="mt-6" aria-live="polite" aria-busy={busy}>
        {error && !data ? (
          <div className="rounded-xl border border-destructive/40 bg-destructive/10 p-5 text-sm">
            <p className="font-semibold text-destructive">No se pudo consultar YouTube</p>
            <p className="mt-1">{(error as Error).message}</p>
            <Button size="sm" variant="secondary" className="mt-3" onClick={() => void refetch()}><RefreshCw /> Reintentar</Button>
          </div>
        ) : isLoading ? (
          <>
            <p className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Buscando en YouTube y leyendo la ficha de cada video… la primera vez tarda entre 5 y 20 s.
            </p>
            <div className="grid gap-3 lg:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-44 rounded-xl" />)}</div>
          </>
        ) : data && (
          <>
            <p className={cn("mb-3 text-xs text-muted-foreground transition-opacity", busy && "opacity-50")}>
              {data.items.length} videos, del más al menos prometedor · {meta!.queries.length > 1 ? `temas: ${meta!.queries.join(", ")}` : `búsqueda: ${meta!.queries[0]}`}
              {meta!.cached ? " · de la caché (menos de 30 min)" : ""}{hidden ? ` · ocultos: ${hidden}` : ""}
            </p>
            {data.items.length === 0 ? (
              <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
                Nada con potencial para esta búsqueda. Prueba con otro tema, «Este mes», «Cualquier duración» o «Cualquier idioma».
              </p>
            ) : (
              <ul className={cn("grid gap-3 lg:grid-cols-2", busy && "opacity-60")}>
                {data.items.map((i) => <Card key={i.id} item={i} onCreate={create} creating={creating === i.id} />)}
              </ul>
            )}
          </>
        )}
      </section>
    </div>
  );
}
