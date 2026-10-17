"use client";

import { AlertTriangle, BadgeCheck, Loader2, Search, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InputControl, InputWrapper } from "@/components/ui/input";
import { useSourceInfo } from "@/lib/client";
import { duration as fmtDuration } from "@/lib/format";
import { parseSource } from "@/lib/sources";
import type { KickChannelVods } from "@/lib/types";
import { FavoriteChips } from "./favorite-chips";
import { count, VideoRow } from "./source-video-row";

const SLUG = /^[A-Za-z0-9_-]{2,40}$/;

/** «westcol», «@westcol», «kick.com/westcol» o un enlace completo → «westcol» (o null). */
export function kickUser(raw: string): string | null {
  const t = raw.trim().replace(/^@/, "");
  if (!t) return null;
  if (SLUG.test(t)) return t.toLowerCase();
  const src = parseSource(t);
  return src?.type === "kick" && src.channel ? src.channel.toLowerCase() : null;
}

function day(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("es", { day: "numeric", month: "short" });
}

function Vod({ vod, selected, onPick }: { vod: KickChannelVods["vods"][number]; selected: boolean; onPick: () => void }) {
  return (
    <VideoRow
      title={vod.title}
      thumbnail={vod.thumbnail}
      badge={vod.live ? "En vivo" : fmtDuration(vod.durationSec)}
      left={day(vod.createdAt)}
      right={vod.views ? `${count(vod.views)} vistas` : undefined}
      selected={selected}
      blocked={vod.live ? "Es un directo en curso: espera a que termine" : null}
      onPick={onPick}
    />
  );
}

/**
 * Videos de un streamer de Kick: escribes su usuario (westcol), ves sus VODs
 * disponibles (Kick los borra a los pocos días) y eliges uno. La elección pasa
 * al formulario, donde se escoge el tramo y se crean los clips.
 */
export function KickBrowser({ user, onUser, selectedId, onPick }: {
  user: string;
  onUser: (u: string) => void;
  /** Id del VOD que ya está en el formulario (para marcarlo). */
  selectedId: string | null;
  onPick: (url: string, thumbnail: string | null) => void;
}) {
  const [text, setText] = useState(user);
  const [seen, setSeen] = useState(user);
  const [invalid, setInvalid] = useState(false);
  if (user !== seen) { // el usuario también puede llegar desde el enlace pegado arriba
    setSeen(user);
    setText(user);
  }

  const query = useSourceInfo(user ? `https://kick.com/${user}` : "", !!user);
  const data = query.data?.type === "kick" && query.data.kind === "channel" ? query.data : null;

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const u = kickUser(text);
    setInvalid(!u);
    if (u) onUser(u);
  }

  return (
    <div className="flex min-h-0 flex-col">
      <h2 className="font-condensed px-5 pt-4 text-[22px] leading-none font-bold">Videos de un streamer de Kick</h2>

      <form onSubmit={submit} className="px-5 pt-3.5">
        <InputWrapper className="h-12 gap-1.5 pr-1.5 pl-4" aria-invalid={invalid || undefined} data-state={invalid ? "error" : undefined}>
          <span aria-hidden className="text-muted-foreground">@</span>
          <InputControl
            value={text.replace(/^@/, "")}
            onChange={(e) => { setText(e.target.value); setInvalid(false); }}
            placeholder="westcol"
            aria-label="Usuario de Kick"
            aria-invalid={invalid}
            maxLength={80}
            autoCapitalize="off"
            spellCheck={false}
          />
          <Button type="submit" size="sm" disabled={query.isFetching && !!user}>
            {query.isFetching && !!user ? <Loader2 className="animate-spin" /> : <Search />} Ver videos
          </Button>
        </InputWrapper>
        {invalid && <p className="mt-1.5 px-2 text-xs text-destructive">Escribe el usuario (westcol) o el enlace de su canal de Kick.</p>}
      </form>

      <FavoriteChips platform="kick" noun="streamer" current={user} currentLabel={data?.profile?.name ?? (data ? data.channel : undefined)} onPick={onUser} />

      <div className="min-h-0 flex-1 px-3 pt-3 pb-3">
        {!user ? null : query.isFetching && !data ? (
          <p className="flex items-center gap-2 px-3 py-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Buscando los videos de {user}…</p>
        ) : query.error ? (
          <p className="flex items-start gap-2 px-3 py-6 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{(query.error as Error).message}</p>
        ) : data ? (
          <>
            <div className="flex items-center gap-3 px-2 pb-2">
              {data.profile?.avatar ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={data.profile.avatar} alt="" referrerPolicy="no-referrer" className="size-11 shrink-0 rounded-full bg-well object-cover" />
              ) : (
                <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-full bg-well text-lg font-bold">{user[0]?.toUpperCase()}</span>
              )}
              <div className="min-w-0">
                <p className="flex items-center gap-1 truncate font-semibold">
                  {data.profile?.name ?? data.channel}
                  {data.profile?.verified && <BadgeCheck className="size-4 shrink-0 text-[#53fc18]" aria-label="Canal verificado" />}
                </p>
                <p className="text-xs text-muted-foreground">
                  {data.profile?.followers ? `${count(data.profile.followers)} seguidores` : `${data.vods.length} videos disponibles`}
                </p>
              </div>
              {data.profile?.live && (
                <Badge variant="danger" size="sm" className="ml-auto shrink-0 gap-1.5" title={data.profile.live}>
                  <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-current" /> En vivo
                </Badge>
              )}
            </div>
            {data.vods.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">Este canal no tiene videos disponibles ahora mismo.</p>
            ) : (
              <ul className="max-h-[27rem] space-y-1 overflow-y-auto overscroll-contain px-0.5">
                {data.vods.map((v) => <Vod key={v.id} vod={v} selected={v.id === selectedId} onPick={() => onPick(v.url, v.thumbnail)} />)}
              </ul>
            )}
          </>
        ) : null}
      </div>
      {user && (
        <Button type="button" variant="ghost" size="xs" className="mx-4 mb-3 -mt-1 self-start text-muted-foreground" onClick={() => { onUser(""); setText(""); }}>
          <X /> Quitar streamer
        </Button>
      )}
    </div>
  );
}
