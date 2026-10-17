"use client";

import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { useFavorites } from "@/lib/client";
import { type FavPlatform, isFavorite } from "@/lib/favorites";
import { cn } from "@/lib/utils";

/**
 * Los favoritos de una plataforma como botones: un clic abre sus videos. El canal que se está viendo y
 * todavía no es favorito ofrece «Guardar» (queda en data/favorites.json, no en el navegador); la × de
 * cada botón lo quita.
 */
export function FavoriteChips({ platform, current, currentLabel, onPick, noun }: {
  platform: FavPlatform;
  /** Clave del canal que se está viendo ("" si ninguno). */
  current: string;
  /** Nombre con el que se guardaría (el del perfil, cuando ya cargó). */
  currentLabel?: string;
  onPick: (key: string) => void;
  /** «streamer» o «canal», para los textos. */
  noun: string;
}) {
  const { favorites, add, remove } = useFavorites();
  const list = favorites?.[platform];
  const canSave = !!current && !!list && !isFavorite(list, current);

  const fail = (e: unknown) => toast.error((e as Error).message);

  if (!list) return null;
  if (!list.length && !canSave) {
    return <p className="px-5 pt-2.5 text-xs text-muted-foreground">Guarda tus {noun}s favoritos para abrirlos con un clic.</p>;
  }
  return (
    <div role="group" aria-label={`${noun}s favoritos`} className="flex flex-wrap items-center gap-1.5 px-5 pt-2.5">
      {list.map((f) => {
        const active = current.toLowerCase() === f.key.toLowerCase();
        return (
          <span
            key={f.key}
            className={cn(
              "inline-flex h-7 items-center rounded-full pl-3 text-xs font-medium",
              active ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground",
            )}
          >
            <button
              type="button"
              onClick={() => onPick(f.key)}
              aria-pressed={active}
              title={`Ver los videos de ${f.label}`}
              className="max-w-[10rem] truncate rounded-full py-1 pr-1.5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {f.label}
            </button>
            <button
              type="button"
              onClick={() => remove.mutate({ platform, key: f.key }, { onError: fail })}
              aria-label={`Quitar a ${f.label} de los favoritos`}
              title="Quitar de favoritos"
              className="mr-0.5 grid size-5 place-items-center rounded-full opacity-60 outline-none hover:bg-black/15 hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="size-3" />
            </button>
          </span>
        );
      })}
      {canSave && (
        <button
          type="button"
          onClick={() => add.mutate({ platform, favorite: { key: current, label: currentLabel || current } }, { onError: fail })}
          disabled={add.isPending}
          className="inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-[var(--v-edge)] px-2.5 text-xs font-medium text-foreground outline-none hover:border-primary hover:text-primary focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          <Plus className="size-3" /> Guardar {currentLabel || current}
        </button>
      )}
    </div>
  );
}
