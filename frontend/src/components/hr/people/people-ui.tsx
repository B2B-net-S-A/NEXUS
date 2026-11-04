import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { TodayTone } from "./directory-view";

const PILL_TONE: Record<TodayTone, string> = {
  success: "bg-success-muted text-success-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
  warning: "bg-warning-muted text-warning-muted-foreground",
  neutral: "bg-muted text-muted-foreground",
};

/** Pigułka stanu (forma, „odchodzi 30.11”, „przerwa do śr 21.10”). */
export function TonePill({
  tone,
  children,
  className,
}: {
  tone: TodayTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        PILL_TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Chip filtra z licznikiem (dział, forma, „Dziś nieobecni”). */
export function FilterChip({
  active,
  onClick,
  count,
  dotClass,
  children,
}: {
  active: boolean;
  onClick: () => void;
  count?: number;
  dotClass?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] font-medium transition-colors",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-accent",
      )}
    >
      {dotClass ? <span aria-hidden className={cn("h-2 w-2 rounded-full", dotClass)} /> : null}
      {children}
      {count != null ? <span className="font-semibold opacity-70">{count}</span> : null}
    </button>
  );
}
