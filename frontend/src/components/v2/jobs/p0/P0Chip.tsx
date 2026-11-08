"use client";

import { Flame } from "lucide-react";

import { p0OverdueLabel, p0Remaining, p0UntilLabel } from "@/lib/job-p0";
import { cn } from "@/lib/utils";

import { useNow } from "./useNow";

export interface P0ChipProps {
  /** `p0_until` z serwera; po terminie plakietka „P0 · minęło …” z przerywaną ramką. */
  until: string | null | undefined;
  reason?: string | null;
  size?: "sm" | "md";
  className?: string;
}

const SIZE: Record<NonNullable<P0ChipProps["size"]>, string> = {
  sm: "h-5 px-1.5 text-[11px]",
  md: "h-6 px-2 text-xs",
};

/**
 * Plakietka P0 (27.10.2026): pełny czerwony z płomieniem i odliczaniem —
 * „P0 · 23 h”. Stoi w miejscu plakietki P1 (wiersz listy, Daily, nagłówek).
 */
export function P0Chip({ until, reason, size = "sm", className }: P0ChipProps) {
  const now = useNow();
  if (!until || !Number.isFinite(Date.parse(until))) return null;
  const left = p0Remaining(until, now);
  if (!left) {
    // 06.11.2026: termin minął, P0 trwa do decyzji Head of Recruitment.
    const overdueTitle = `P0 po terminie (${p0UntilLabel(until, now)}) — trwa, dopóki ktoś go nie przedłuży albo nie zakończy${reason ? `: ${reason}` : ""}`;
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-md border-2 border-dashed border-destructive bg-card font-bold text-destructive",
          SIZE[size],
          className,
        )}
        title={overdueTitle}
        data-testid="p0-chip"
        data-overdue="true"
      >
        <Flame className="h-3 w-3 shrink-0" aria-hidden="true" />
        <span aria-hidden="true">P0 · {p0OverdueLabel(until, now)}</span>
        <span className="sr-only">{overdueTitle}</span>
      </span>
    );
  }
  const title = `P0 — ultrapilne do ${p0UntilLabel(until, now)}${reason ? `: ${reason}` : ""}`;
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded-md bg-destructive font-bold text-destructive-foreground",
        SIZE[size],
        className,
      )}
      title={title}
      data-testid="p0-chip"
    >
      <Flame className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span aria-hidden="true">P0 · {left}</span>
      <span className="sr-only">{title}</span>
    </span>
  );
}
