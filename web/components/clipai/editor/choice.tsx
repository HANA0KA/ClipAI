"use client";

import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

/** Control segmentado de una sola opción (nunca queda vacío). */
export function Choice<T extends string>({ value, options, onChange, label, disabled }: {
  value: T;
  options: { value: T; label: React.ReactNode; hint?: string; disabled?: boolean }[];
  onChange: (v: T) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="pink"
      size="sm"
      value={value}
      onValueChange={(v) => v && onChange(v as T)}
      aria-label={label}
      disabled={disabled}
      className="flex-wrap"
    >
      {options.map((o) => (
        <ToggleGroupItem
          key={o.value}
          value={o.value}
          title={o.hint}
          disabled={o.disabled}
        >
          {o.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/** Deslizador con etiqueta y valor. */
export function Knob({ label, value, min, max, step, format, onChange, disabled }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-[96px_1fr_56px] items-center gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Slider
        value={[value]}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onValueChange={([v]) => onChange(v)}
        aria-label={label}
      />
      <span className="tabular text-right text-xs">{format(value)}</span>
    </div>
  );
}
