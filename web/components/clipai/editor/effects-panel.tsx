"use client";

import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { type AudioSettings, DEFAULT_EFFECTS, type Effects, isDefaultEffects } from "@/lib/edit-doc";
import { Knob } from "./choice";

interface Props {
  effects: Effects;
  audio: AudioSettings;
  punch: boolean;
  onPunch: (on: boolean) => void;
  autoFraming: boolean;
  onEffects: (patch: Partial<Effects>, key?: string) => void;
  onAudio: (patch: Partial<AudioSettings>, key?: string) => void;
}

const pct = (v: number) => `${Math.round(v)} %`;

function Row({ id, title, hint, children }: { id: string; title: string; hint: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      {children}
      <Label htmlFor={id} className="block text-sm leading-snug font-normal">
        {title}
        <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
      </Label>
    </div>
  );
}

/** Color, audio y acercamientos. */
export function EffectsPanel({
  effects, audio, punch, onPunch, autoFraming, onEffects, onAudio,
}: Props) {
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Imagen</h3>
          <Button variant="ghost" size="sm" disabled={isDefaultEffects(effects)} onClick={() => onEffects(DEFAULT_EFFECTS)}>
            <RotateCcw /> Restablecer
          </Button>
        </div>
        <Knob label="Brillo" value={effects.brightness} min={40} max={180} step={1} format={pct}
          onChange={(brightness) => onEffects({ brightness }, "brightness")} />
        <Knob label="Contraste" value={effects.contrast} min={40} max={180} step={1} format={pct}
          onChange={(contrast) => onEffects({ contrast }, "contrast")} />
        <Knob label="Saturación" value={effects.saturation} min={0} max={220} step={1} format={pct}
          onChange={(saturation) => onEffects({ saturation }, "saturation")} />
        <Knob label="Tono" value={effects.hue} min={-180} max={180} step={1} format={(v) => `${Math.round(v)}°`}
          onChange={(hue) => onEffects({ hue }, "hue")} />
        <Knob label="Desenfoque" value={effects.blur} min={0} max={8} step={0.1} format={(v) => v.toFixed(1)}
          onChange={(blur) => onEffects({ blur }, "blur")} />
        <p className="text-xs text-muted-foreground">
          Los subtítulos no se ven afectados. El render usa la misma fórmula que la vista previa; el tono puede
          variar un poco.
        </p>
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Movimiento</h3>
        <Row
          id="punch"
          title="Acercamiento en palabras fuertes"
          hint={autoFraming
            ? "Un acercamiento corto (12 %) en las palabras que destacaste, las cifras y las palabras fuertes; como mucho uno cada 18 s. No se aplica sobre tramos de dos personas ni con fondo desenfocado."
            : "Solo con encuadre automático: en el manual el encuadre lo decides tú."}
        >
          <Switch id="punch" checked={punch && autoFraming} disabled={!autoFraming} onCheckedChange={onPunch} />
        </Row>
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Audio</h3>
        <Knob label="Volumen" value={audio.volume * 100} min={0} max={200} step={1} format={pct} disabled={audio.muted}
          onChange={(v) => onAudio({ volume: v / 100 }, "volume")} />
        <Row id="mute" title="Silenciar" hint="El clip sale sin sonido (p. ej. para poner música en la app).">
          <Switch id="mute" checked={audio.muted} onCheckedChange={(muted) => onAudio({ muted })} />
        </Row>
        <p className="text-xs text-muted-foreground">
          El volumen se aplica después de normalizar a {"−14"} LUFS. En la vista previa no pasa del 100 %.
        </p>
      </section>

    </div>
  );
}
