"use client";

import { cn } from "@/lib/utils";
import type { KpiState } from "@/lib/api";

interface Props {
  /** Wartość 0-100+ (może przekroczyć 100 przy over-hit) */
  progressPct: number;
  state: KpiState;
  /** Sticky label (np. "8/10") */
  label?: string;
  /** Krótki tytuł (np. "Aktywności dziś") */
  title?: string;
  /** Kompaktowy variant (widget w topbarze) vs normalny (drawer/dashboard). */
  variant?: "compact" | "full";
  className?: string;
}

const STATE_BAR_CLASS: Record<KpiState, string> = {
  hit: "bg-emerald-500",
  ahead: "bg-emerald-500",
  on_track: "bg-[hsl(var(--accent))]",
  behind: "bg-amber-500",
  missed: "bg-neutral-400",
};

const STATE_TEXT_CLASS: Record<KpiState, string> = {
  hit: "text-emerald-700",
  ahead: "text-emerald-700",
  on_track: "text-[hsl(var(--accent))]",
  behind: "text-amber-700",
  missed: "text-neutral-500",
};

/**
 * Reusable progress bar dla widget'a KPI + drawera.
 * Kolor paska i tekstu zależy od state'u.
 */
export function KpiProgressBar({
  progressPct,
  state,
  label,
  title,
  variant = "full",
  className,
}: Props) {
  const clamped = Math.min(100, Math.max(0, progressPct));
  const trackClass =
    variant === "compact" ? "h-1.5" : "h-2";
  const rootPad =
    variant === "compact" ? "gap-0.5" : "gap-1";

  return (
    <div className={cn("flex flex-col min-w-0", rootPad, className)}>
      {(title || label) && (
        <div className="flex items-center justify-between gap-2 text-xs">
          {title ? (
            <span className="truncate text-[hsl(var(--text-muted))]">
              {title}
            </span>
          ) : (
            <span />
          )}
          {label && (
            <span
              className={cn(
                "font-medium tabular-nums shrink-0",
                STATE_TEXT_CLASS[state],
              )}
            >
              {label}
            </span>
          )}
        </div>
      )}
      <div
        className={cn(
          "w-full rounded-full bg-[hsl(var(--bg-canvas))] overflow-hidden",
          trackClass,
        )}
        aria-valuenow={Math.round(progressPct)}
        aria-valuemin={0}
        aria-valuemax={100}
        role="progressbar"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            STATE_BAR_CLASS[state],
          )}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
