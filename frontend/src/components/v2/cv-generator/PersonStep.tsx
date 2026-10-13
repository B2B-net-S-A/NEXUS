"use client";

import { StepCard, initials } from "./GeneratorParts";
import type { CvCandidateOption } from "./useCvGenerator";

export interface PersonStepProps {
  candidate: CvCandidateOption;
}

/**
 * Krok 1 — osoba, dla której powstaje CV. Generator żyje tylko w oknie
 * z rekrutacji i profilu kandydata, więc osoba jest zawsze ustalona z góry
 * (od 13.10.2026 bez wyszukiwania, „Zmień” i pliku osoby spoza bazy).
 */
export function PersonStep({ candidate }: PersonStepProps) {
  return (
    <StepCard step={1} title="Kandydat">
      <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
        <span
          aria-hidden
          className="inline-flex h-10 w-10 flex-none items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
        >
          {initials(candidate.full_name)}
        </span>
        <p className="min-w-0 flex-1 truncate font-semibold text-foreground">{candidate.full_name}</p>
      </div>
    </StepCard>
  );
}
