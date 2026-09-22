"use client";

import { cn } from "@/lib/utils";
import type { CandidateFilters } from "@/lib/url-filters";
import { QUICK_FILTERS, toggleQuickFilter } from "@/lib/candidate-quick-filters";

/**
 * Gotowe skróty nad listą kandydatów — jeden klik ustawia kilka filtrów,
 * drugi je zdejmuje. Skrót świeci, dopóki jego filtry są ustawione (także gdy
 * ustawiono je w panelu), więc stan listy widać bez otwierania filtrów.
 */
export function CandidateQuickFilters({
  filters,
  onPatch,
  today = new Date(),
}: {
  filters: CandidateFilters;
  onPatch: (patch: Partial<CandidateFilters>) => void;
  today?: Date;
}) {
  return (
    <div role="group" aria-label="Gotowe skróty" className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-xs font-medium text-muted-foreground">Szybko:</span>
      {QUICK_FILTERS.map((quick) => {
        const active = quick.isActive(filters, today);
        return (
          <button
            key={quick.id}
            type="button"
            aria-pressed={active}
            title={quick.description}
            onClick={() => onPatch(toggleQuickFilter(quick, filters, today))}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-foreground hover:border-primary/50 hover:bg-accent",
            )}
          >
            {quick.label}
          </button>
        );
      })}
    </div>
  );
}
