"use client";

import { Move, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type Aspect, DEFAULT_FRAMING, type Fit, type Framing } from "@/lib/edit-doc";
import type { LayoutMode } from "@/lib/types";
import { Choice, Knob } from "./choice";
import { LayoutPicker } from "./layout-picker";

interface Props {
  framing: Framing;
  layoutMode: LayoutMode;
  onFraming: (patch: Partial<Framing>, key?: string) => void;
  onLayout: (mode: LayoutMode) => void;
}

/** Formato de salida y encuadre: automático (reencuadre por escenas) o manual. */
export function FramingPanel({ framing, layoutMode, onFraming, onLayout }: Props) {
  const original = framing.aspect === "original";
  const manual = framing.mode === "manual" || original;
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">Formato</p>
        <Choice<Aspect>
          label="Formato de salida"
          value={framing.aspect}
          onChange={(aspect) => onFraming({ aspect })}
          options={[
            { value: "vertical", label: "Vertical 9:16", hint: "1080×1920: TikTok, Reels, Shorts" },
            { value: "square", label: "Cuadrado 1:1", hint: "1080×1080" },
            { value: "original", label: "Original", hint: "La proporción del video (lado largo ≤ 1920)" },
          ]}
        />
      </div>

      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">Encuadre</p>
        <Choice<"auto" | "manual">
          label="Tipo de encuadre"
          value={manual ? "manual" : "auto"}
          onChange={(mode) => onFraming({ mode })}
          options={[
            { value: "auto", label: "Automático", hint: "Sigue a quien habla, escena por escena", disabled: original },
            { value: "manual", label: "Manual", hint: "Tú eliges zoom y posición" },
          ]}
        />
        {original && <p className="text-xs text-muted-foreground">En formato original no hay reencuadre automático.</p>}
      </div>

      {manual ? (
        <div className="space-y-4">
          <Choice<Fit>
            label="Ajuste del video"
            value={framing.fit}
            onChange={(fit) => onFraming({ fit })}
            options={[
              { value: "cover", label: "Llenar", hint: "Ocupa todo el cuadro y recorta lo que sobra" },
              { value: "contain", label: "Encajar", hint: "Se ve entero, con fondo desenfocado" },
            ]}
          />
          <Knob label="Zoom" value={framing.zoom} min={1} max={3} step={0.01} format={(v) => `${v.toFixed(2)}×`}
            onChange={(zoom) => onFraming({ zoom }, "zoom")} />
          <div className="flex flex-wrap items-center gap-3">
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Move className="size-3.5" /> Arrastra la vista previa para mover al sujeto.
            </p>
            <Button variant="ghost" size="sm" onClick={() => onFraming({ x: DEFAULT_FRAMING.x, y: DEFAULT_FRAMING.y, zoom: 1 })}>
              <RotateCcw /> Centrar
            </Button>
          </div>
        </div>
      ) : (
        <LayoutPicker value={layoutMode} onChange={onLayout} />
      )}
    </div>
  );
}
