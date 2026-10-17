"use client";

import { AlertTriangle, BadgeCheck, Loader2, Search, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { InputControl, InputWrapper } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useSourceInfo } from "@/lib/client";
import { duration as fmtDuration } from "@/lib/format";
import { youtubeChannelKey } from "@/lib/sources";
import type { YoutubeChannelVideos } from "@/lib/types";
import { FavoriteChips } from "./favorite-chips";
import { count, VideoRow } from "./source-video-row";

function blockedReason(v: YoutubeChannelVideos["videos"][number], maxMinutes: number): string | null {
  if (v.live) return "Es un directo en curso o programado: espera a que termine";
  if (v.membersOnly) return "Es solo para miembros del canal";
  if (v.tooLong) return `Dura ${Math.round(v.durationSec / 60)} min y el máximo es ${maxMinutes} min`;
  return null;
}

/**
 * Videos de un canal de YouTube: escribes su @usuario (o pegas el enlace del canal), ves sus videos
 * recientes —o sus directos ya terminados— y eliges uno. La elección pasa al formulario, que crea los
 * clips. YouTube no permite bajar un tramo: se baja el video entero (hasta el máximo de minutos).
 */
export function YoutubeBrowser({ channel, onChannel, selectedId, onPick }: {
  /** Clave del canal que se está viendo: «@handle», «channel/UC…»… ("" si ninguno). */
  channel: string;
  onChannel: (key: string) => void;
  /** Id del video que ya está en el formulario (para marcarlo). */
  selectedId: string | null;
  onPick: (url: string) => void;
}) {
  const [text, setText] = useState(channel);
  const [seen, setSeen] = useState(channel);
  const [invalid, setInvalid] = useState(false);
  const [tab, setTab] = useState<"videos" | "streams">("videos");
  if (channel !== seen) { // el canal también puede llegar desde el enlace pegado arriba o desde un favorito
    setSeen(channel);
    setText(channel);
  }

  const query = useSourceInfo(channel ? `https://www.youtube.com/${channel}` : "", !!channel, tab);
  const data = query.data?.type === "youtube" && query.data.kind === "channel" ? query.data : null;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const key = youtubeChannelKey(text, true);
    setInvalid(!key);
    if (key) onChannel(key);
  }

  const anyTooLong = !!data?.videos.some((v) => v.tooLong);

  return (
    <div className="flex min-h-0 flex-col">
      <h2 className="font-condensed px-5 pt-4 text-[22px] leading-none font-bold">Videos de un canal de YouTube</h2>

      <form onSubmit={submit} className="px-5 pt-3.5">
        <InputWrapper className="h-12 gap-1.5 pr-1.5 pl-4" aria-invalid={invalid || undefined} data-state={invalid ? "error" : undefined}>
          <InputControl
            value={text}
            onChange={(e) => { setText(e.target.value); setInvalid(false); }}
            placeholder="@luisitocomunica o el enlace del canal"
            aria-label="Canal de YouTube"
            aria-invalid={invalid}
            maxLength={120}
            autoCapitalize="off"
            spellCheck={false}
          />
          <Button type="submit" size="sm" disabled={query.isFetching && !!channel}>
            {query.isFetching && !!channel ? <Loader2 className="animate-spin" /> : <Search />} Ver videos
          </Button>
        </InputWrapper>
        {invalid && <p className="mt-1.5 px-2 text-xs text-destructive">Escribe el @usuario del canal o pega su enlace de YouTube.</p>}
      </form>

      <FavoriteChips platform="youtube" noun="canal" current={channel} currentLabel={data?.profile.name} onPick={onChannel} />

      <div className="min-h-0 flex-1 px-3 pt-3 pb-3">
        {!channel ? null : query.isFetching && !data ? (
          <p className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Buscando los videos de {channel.replace(/^(channel|c|user)\//, "")}…</p>
        ) : query.error ? (
          <p className="flex items-start gap-2 px-3 py-6 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{(query.error as Error).message}</p>
        ) : data ? (
          <>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2 pb-2">
              {data.profile.avatar ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={data.profile.avatar} alt="" referrerPolicy="no-referrer" className="size-11 shrink-0 rounded-full bg-well object-cover" />
              ) : (
                <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-full bg-well text-lg font-bold">{data.profile.name[0]?.toUpperCase()}</span>
              )}
              <div className="min-w-[9rem] flex-1">
                <p className="flex items-center gap-1 truncate font-semibold">
                  {data.profile.name}
                  {data.profile.verified && <BadgeCheck className="size-4 shrink-0 text-muted-foreground" aria-label="Canal verificado" />}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {data.profile.followers ? `${count(data.profile.followers)} suscriptores` : data.profile.handle ?? data.channel}
                </p>
              </div>
              <ToggleGroup type="single" variant="pink" size="sm" value={tab} aria-label="Qué videos ver" className="ml-auto shrink-0"
                onValueChange={(v) => v && setTab(v as "videos" | "streams")}>
                <ToggleGroupItem value="videos">Videos</ToggleGroupItem>
                <ToggleGroupItem value="streams">Directos</ToggleGroupItem>
              </ToggleGroup>
            </div>
            {data.videos.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                {data.missingTab ? "Este canal no tiene directos guardados." : "Este canal no tiene videos disponibles ahora mismo."}
              </p>
            ) : (
              <>
                <ul className="max-h-[27rem] space-y-1 overflow-y-auto overscroll-contain px-0.5">
                  {data.videos.map((v) => (
                    <VideoRow
                      key={v.id}
                      title={v.title}
                      thumbnail={v.thumbnail}
                      badge={v.live ? "En vivo" : fmtDuration(v.durationSec)}
                      left={v.tooLong ? "Muy largo" : undefined}
                      right={v.views ? `${count(v.views)} vistas` : undefined}
                      selected={v.id === selectedId}
                      blocked={blockedReason(v, data.maxMinutes)}
                      onPick={() => onPick(v.url)}
                    />
                  ))}
                </ul>
                {anyTooLong && (
                  <p className="px-3 pt-2 text-xs text-muted-foreground">
                    Los videos de más de {data.maxMinutes} min no se pueden elegir: YouTube no deja bajar solo un tramo.
                  </p>
                )}
              </>
            )}
          </>
        ) : null}
      </div>
      {channel && (
        <Button type="button" variant="ghost" size="xs" className="mx-4 mb-3 -mt-1 self-start text-muted-foreground" onClick={() => { onChannel(""); setText(""); }}>
          <X /> Quitar canal
        </Button>
      )}
    </div>
  );
}
