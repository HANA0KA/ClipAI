"use client";

import * as React from "react";
import { Slot, Slottable } from "@radix-ui/react-slot";
import { Spinner } from "@/components/ui/spinner";
import { MotionPresence, MotionSurface } from "@/components/ui/presence";
import { useFlowPress } from "@/lib/cojeev-motion/flow-press";
import { useMorph } from "@/lib/cojeev-motion/use-morph";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { controlRadiusStyle, type ControlRadius } from "@/lib/cojeev/control-appearance";

const buttonVariants = cva(
  "v-btn [display:inline-flex] items-center justify-center gap-[var(--s-2)] h-[var(--ctl-md)] px-[var(--s-5)] py-0 rounded-[var(--r-pill)] text-[length:var(--fs-control)] font-[number:var(--fw-control)] leading-none whitespace-nowrap bg-[var(--primary)] text-[color:var(--primary-foreground)] motion-safe:active:[transform:translateY(1px)] [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "",
        accent:
          "-accent bg-[var(--v-pink)] text-[color:var(--v-on-accent)] hover:bg-[var(--v-pink-deep)]",
        // ClipAI: la variante secundaria es la superficie elevada, no el azul de cojeev.
        secondary:
          "-secondary bg-[var(--v-beige)] text-[color:var(--v-text)] hover:bg-[color-mix(in_oklab,var(--v-beige)_84%,var(--v-text))]",
        ghost:
          "-ghost bg-transparent text-[color:var(--v-text)] hover:bg-[var(--v-beige)]",
        outline:
          "-outline bg-transparent text-[color:var(--v-text)] [box-shadow:inset_0_0_0_1px_var(--v-edge)] hover:bg-[var(--v-beige-2)]",
        danger:
          "-danger bg-[var(--v-danger-fill)] text-[color:var(--destructive-foreground)]",
        // ClipAI: acción destructiva discreta (tinte de peligro), sin el relleno rojo pleno.
        destructive:
          "-destructive bg-[var(--v-danger-soft)] text-[color:var(--v-danger-ink)] hover:bg-[color-mix(in_oklab,var(--v-danger-soft)_78%,var(--v-danger-ink))]",
        link: "-link h-auto px-0 bg-transparent text-[color:var(--v-accent-ink)] underline-offset-4 hover:underline",
        block: "-block w-full",
      },
      size: {
        default: "",
        xs: "-xs h-6 px-[var(--s-2)] gap-1 text-[length:var(--fs-meta)] [&_svg:not([class*='size-'])]:size-3",
        sm: "-sm h-[var(--ctl-sm)] px-[var(--s-4)] text-[length:var(--fs-small)]",
        lg: "-lg h-[var(--ctl-lg)] px-[var(--s-6)] text-[length:var(--fs-body)]",
        icon: "-icon size-[var(--ctl-md)] px-0",
        "icon-lg": "-icon size-[var(--ctl-lg)] px-0",
        "icon-sm": "-icon size-[var(--ctl-sm)] px-0",
        "icon-xs": "-icon size-6 px-0 [&_svg:not([class*='size-'])]:size-3",
      },
      shape: { pill: "", card: "-card" },
      fullWidth: { true: "-block w-full", false: "" },
    },
    defaultVariants: { variant: "default", size: "default", shape: "pill", fullWidth: false },
  },
);

type ButtonProps = Omit<React.ComponentProps<"button">, "ref"> &
  VariantProps<typeof buttonVariants> & {
    /** Use one native element (for example a link) as the interactive root. */
    asChild?: boolean;
    ref?: React.Ref<HTMLButtonElement | HTMLAnchorElement>;
    loading?: boolean;
    loadingIndicator?: React.ReactNode;
    radius?: ControlRadius;
  };

function Button({
  ref: externalRef,
  className,
  variant,
  size,
  shape,
  radius, style,
  fullWidth,
  loading,
  loadingIndicator,
  children,
  asChild = false,
  disabled,
  type = "button",
  "aria-busy": ariaBusy,
  "aria-disabled": ariaDisabled,
  onClick,
  onClickCapture,
  onAuxClickCapture,
  ...props
}: ButtonProps) {
  const morphRef = useMorph<HTMLButtonElement | HTMLAnchorElement>("buttons", externalRef);
  const pressRef = useFlowPress(morphRef);
  const busy = loading ?? (ariaBusy === true || ariaBusy === "true");
  const blocked = disabled || busy || ariaDisabled === true || ariaDisabled === "true";
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      ref={pressRef}
      data-slot="button"
      data-part="root"
      data-r={shape === "card" ? 12 : undefined}
      data-control-shape={shape ?? undefined}
      style={{ ...style, ...controlRadiusStyle(radius) }}
      data-state={disabled ? "disabled" : busy ? "busy" : "rest"}
      type={asChild ? undefined : type}
      disabled={asChild ? undefined : disabled}
      aria-busy={busy || undefined}
      aria-disabled={blocked || undefined}
      onClickCapture={(event) => {
        // Stop a slotted link before its own router/click handler can activate.
        if (asChild && blocked) { event.preventDefault(); event.stopPropagation(); return; }
        onClickCapture?.(event);
      }}
      onAuxClickCapture={(event) => {
        if (asChild && blocked) { event.preventDefault(); event.stopPropagation(); return; }
        onAuxClickCapture?.(event);
      }}
      onClick={(event) => {
        if (blocked) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      className={cn(
        buttonVariants({ variant, size, shape, fullWidth }),
        "leading-none",
        className,
      )}
      {...props}
      tabIndex={asChild && disabled ? -1 : props.tabIndex}
    >
      <MotionPresence>
        {busy && (
          <MotionSurface key="loading" asChild preset="scale">
            <span
              data-slot="button-loading"
              className="v-btn__loading"
              aria-hidden="true"
            >
              {loadingIndicator ?? <ButtonIndicator />}
            </span>
          </MotionSurface>
        )}
      </MotionPresence>
      {asChild ? <Slottable>{children}</Slottable> : children}
    </Comp>
  );
}

function ButtonIndicator({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <Spinner
      data-slot="button-indicator"
      data-part="indicator"
      data-label=""
      aria-hidden="true"
      className={className}
      {...props}
    />
  );
}

export { Button, ButtonIndicator, buttonVariants };
export type { ButtonProps };
