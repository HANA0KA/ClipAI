import { cn } from "@/lib/utils";

/** Tecla de atajo, discreta, dentro de botones y ayudas. */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded border border-border px-1 font-sans text-[10px] leading-none text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
