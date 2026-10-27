"use client";

import { Flame } from "lucide-react";

import { p0Remaining, p0UntilLabel } from "@/lib/job-p0";
import { cn } from "@/lib/utils";

import { useNow } from "./useNow";

export interface P0ChipProps {
  /** `p0_until` z serwera; po terminie plakietka znika. */
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
  const left = p0Remaining(until, now);
  if (!until || !left) return null;
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
