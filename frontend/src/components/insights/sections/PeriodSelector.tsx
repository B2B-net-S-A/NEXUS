"use client";

import { cn } from "@/lib/utils";

export type Period = "today" | "week" | "month" | "quarter";

export const PERIOD_LABELS: Record<Period, string> = {
  today: "Dziś",
  week: "Bieżący tydzień",
  month: "Bieżący miesiąc",
  quarter: "Bieżący kwartał",
};

const ORDER: Period[] = ["today", "week", "month", "quarter"];

interface Props {
  value: Period;
  onChange: (next: Period) => void;
  className?: string;
}

export function PeriodSelector({ value, onChange, className }: Props) {
  return (
    <div className={cn("inline-flex rounded-md border border-border bg-card overflow-hidden", className)}>
      {ORDER.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onChange(p)}
          className={cn(
            "px-3 py-1.5 text-sm transition-colors whitespace-nowrap",
            value === p
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted"
          )}
          aria-pressed={value === p}
        >
          {PERIOD_LABELS[p]}
        </button>
      ))}
    </div>
  );
}
