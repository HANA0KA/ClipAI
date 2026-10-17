"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { KickBrowser } from "./kick-browser";
import { KickMark, YoutubeMark } from "./source-video-row";
import { YoutubeBrowser } from "./youtube-browser";

export type PanelTab = "kick" | "youtube";

/**
 * El panel de la derecha del inicio: buscar videos por streamer (Kick) o por canal (YouTube), con los
 * favoritos de cada uno como botones. Solo se monta —y solo consulta— la pestaña abierta.
 */
export function SourcePanel({ tab, onTab, kickUser, onKickUser, ytChannel, onYtChannel, kickSelectedId, ytSelectedId, onPickKick, onPickYoutube }: {
  tab: PanelTab;
  onTab: (t: PanelTab) => void;
  kickUser: string;
  onKickUser: (u: string) => void;
  ytChannel: string;
  onYtChannel: (c: string) => void;
  kickSelectedId: string | null;
  ytSelectedId: string | null;
  onPickKick: (url: string, thumbnail: string | null) => void;
  onPickYoutube: (url: string) => void;
}) {
  return (
    <aside aria-label="Buscar videos por streamer o canal" className="flex min-h-0 flex-col rounded-[var(--r-panel)] bg-card pt-3 shadow-[0_24px_60px_-30px_rgb(0_0_0/0.85)]">
      <Tabs value={tab} onValueChange={(v) => onTab(v as PanelTab)} variant="underline" className="flex min-h-0 flex-col">
        <TabsList className="mx-5">
          <TabsTrigger value="kick" className="gap-2"><KickMark /> Kick</TabsTrigger>
          <TabsTrigger value="youtube" className="gap-2"><YoutubeMark /> YouTube</TabsTrigger>
        </TabsList>
        <TabsContent value="kick" className="outline-none">
          <KickBrowser user={kickUser} onUser={onKickUser} selectedId={kickSelectedId} onPick={onPickKick} />
        </TabsContent>
        <TabsContent value="youtube" className="outline-none">
          <YoutubeBrowser channel={ytChannel} onChannel={onYtChannel} selectedId={ytSelectedId} onPick={onPickYoutube} />
        </TabsContent>
      </Tabs>
    </aside>
  );
}
