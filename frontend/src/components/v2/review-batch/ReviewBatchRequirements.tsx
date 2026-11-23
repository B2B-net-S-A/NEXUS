"use client";

import type { KeyEvidence, ReviewBatchRequirements } from "@/lib/api/reviewBatch";
import { cn } from "@/lib/utils";

/**
 * „Musi mieć 7 z 10” na karcie porcji (decyzja Artura 23.11.2026, wariant B,
 * makiety https://claude.ai/artifact/5SJB7AYPZWbFkVKf77jhnN). Ta sama liczba
 * układa kolejkę: więcej spełnionych „musi mieć” = wyżej, „mile widziane”
 * rozstrzyga remis. Dowód z CV jak w „Kluczowe w tej rekrutacji”; klik
 * w pozycję przewija CV po prawej do trafienia.
 */

const MARK: Record<KeyEvidence, { mark: string; tone: string; title: string }> = {
  experience: { mark: "✓", tone: "bg-success/15 text-success", title: "doświadczenie w CV" },
  mention: { mark: "~", tone: "bg-warning/15 text-warning", title: "tylko wzmianka" },
  none: { mark: "✗", tone: "bg-destructive/15 text-destructive", title: "brak śladu w CV" },
};

export function hasRequirementSteps(
  requirements: ReviewBatchRequirements | null | undefined,
): requirements is ReviewBatchRequirements {
  return Boolean(requirements && requirements.must_total + requirements.nice_total > 0);
}

export function ReviewBatchRequirementsBlock({
  requirements,
  onPick,
}: {
  requirements: ReviewBatchRequirements;
  onPick?: (label: string) => void;
}) {
  const missing = requirements.must.filter((row) => row.state === "none").map((row) => row.label);
  const niceMet = requirements.nice.filter((row) => row.state !== "none").map((row) => row.label);
  return (
    <div className="space-y-1.5" data-testid="review-requirements">
      {requirements.must_total > 0 ? (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
            <span className="font-semibold">
              Musi mieć {requirements.must_met} z {requirements.must_total}
            </span>
            {missing.length ? (
              <span className="min-w-0 text-muted-foreground">brak: {missing.join(", ")}</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-1.5" aria-label="Musi mieć">
            {requirements.must.map((row) => {
              const style = MARK[row.state];
              return (
                <button
                  key={row.label}
                  type="button"
                  onClick={() => onPick?.(row.label)}
                  disabled={!onPick}
                  title={`${style.title} · pokaż w CV`}
                  className={cn("rounded px-1.5 py-0.5 text-xs", style.tone)}
                >
                  {style.mark} {row.label}
                </button>
              );
            })}
          </div>
        </>
      ) : null}
      {requirements.nice_total > 0 ? (
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">
            Mile widziane {requirements.nice_met} z {requirements.nice_total}
          </span>
          {niceMet.length ? `: ${niceMet.join(", ")}` : null}
        </p>
      ) : null}
    </div>
  );
}
