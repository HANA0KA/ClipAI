"use client";

import * as React from "react";
import { useMorph } from "@/lib/cojeev-motion/use-morph";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";
import * as Primitive from "@radix-ui/react-tooltip";
import { useFlowAppearance } from "@/lib/cojeev-motion/use-flow";
export type TooltipProps = React.ComponentProps<typeof Primitive.Root>;
export function Tooltip(props: TooltipProps) {
  return <Primitive.Root delayDuration={220} {...props} />;
}
export type TooltipProviderProps = React.ComponentProps<
  typeof Primitive.Provider
>;
export function TooltipProvider(props: TooltipProviderProps) {
  return <Primitive.Provider delayDuration={220} {...props} />;
}
export type TooltipTriggerProps = React.ComponentProps<
  typeof Primitive.Trigger
>;
export function TooltipTrigger(props: TooltipTriggerProps) {
  return (
    <Primitive.Trigger
      data-slot="tooltip-trigger"
      data-part="trigger"
      {...props}
    />
  );
}
export type TooltipPortalProps = React.ComponentProps<typeof Primitive.Portal>;
export function TooltipPortal(props: TooltipPortalProps) {
  return <Primitive.Portal {...props} />;
}
export const tooltipContentVariants = cva(
  "v-tip -show bg-[var(--v-ink)] text-[color:var(--v-on-ink)] text-[length:var(--fs-meta)] leading-[1.3] py-1.5 px-2.5 rounded-[var(--r-sm)] max-w-[260px] z-[var(--z-tooltip)]",
);
export type TooltipContentProps = React.ComponentProps<
  typeof Primitive.Content
> & { portal?: boolean; appearance?: "callout" | "shortcut" | "annotation" };
function TooltipPaint() {
  const ref = useMorph<HTMLSpanElement>("surfaces");
  return (
    <span
      ref={ref}
      className="v-tooltip-paint"
      data-morph="both"
      data-r="css"
      aria-hidden="true"
    />
  );
}
export function TooltipContent({
  className,
  ref,
  children,
  sideOffset = 8,
  portal = true,
  appearance,
  ...props
}: TooltipContentProps) {
  const flowRef = useFlowAppearance<HTMLDivElement>(true, ref, "grow");
  const content = (
    <Primitive.Content
      ref={flowRef}
      data-slot="tooltip-content"
      data-part="content"
      data-appearance={appearance}
      sideOffset={sideOffset}
      className={cn(tooltipContentVariants(), className)}
      {...props}
    >
      {appearance && !props.asChild && <TooltipPaint />}
      {children}
    </Primitive.Content>
  );
  return portal ? <Primitive.Portal>{content}</Primitive.Portal> : content;
}
