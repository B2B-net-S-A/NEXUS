"use client";

import type { RateHistoryChange } from "@/lib/api/contractRateHistoryKsef";
import { monthPl, ratePl } from "../rate-documents/format";

const LEG: Record<string, string> = { client: "klient", cost: "koszt" };

/** Notka pod nazwiskiem na liście kontraktów: faktury KSeF pokazują inną stawkę. */
export function RateHistoryRowNote({
  change,
}: {
  change?: RateHistoryChange | null;
}) {
  if (!change) return null;
  const leg = LEG[change.leg] ?? "stawka";
  const text =
    change.rate !== null && change.rate !== undefined
      ? `faktury (${leg}): ${ratePl(change.rate)} od ${monthPl(change.from)}`
      : `faktury: inna stawka od ${monthPl(change.from)}`;
  return (
    <span
      data-testid="rate-history-row-note"
      title="Faktury KSeF pokazują stawkę, której nie ma w harmonogramie kontraktu"
      className="mt-0.5 inline-block max-w-full truncate rounded border border-warning/40 bg-warning-muted px-1.5 text-[11px] font-medium leading-4 text-warning-muted-foreground"
    >
      {change.count > 1 ? `${text} (+${change.count - 1})` : text}
    </span>
  );
}
