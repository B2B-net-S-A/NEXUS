"use client";

import type { RecruitmentRate } from "@/lib/api/recruitmentRates";
import {
  recruitmentRateLine,
  recruitmentRateNotes,
  type FormRate,
} from "@/lib/recruitment-rate-hint";

/**
 * „Z rekrutacji „X” (DL, data): 165 zł/h · kandydat 140 zł/h” + notka przy
 * różnicy (D7). Tylko informacja — formularz zapisuje niezależnie od niej.
 */
export function RecruitmentRateHint({
  rate,
  revenue,
  cost,
}: {
  rate: RecruitmentRate | null | undefined;
  revenue?: FormRate | null;
  cost?: FormRate | null;
}) {
  const line = recruitmentRateLine(rate);
  if (!line) return null;
  const notes = recruitmentRateNotes(rate, { revenue, cost });
  return (
    <div className="space-y-1 text-xs" data-testid="recruitment-rate-hint">
      <p className="text-muted-foreground">{line}</p>
      {notes.map((note) => (
        <p key={note} role="status" className="text-warning">
          {note}
        </p>
      ))}
    </div>
  );
}
