"use client";

import type { RateDocumentChange } from "@/lib/api/contractRateDocuments";
import { monthPl, ratePl } from "./format";

const KIND_LABEL: Record<string, string> = {
  annex: "aneks",
  contract: "umowa",
};

/** Notka pod nazwiskiem na liście kontraktów: dokument zmienia stawkę od miesiąca. */
export function RateDocumentRowNote({
  change,
}: {
  change?: RateDocumentChange | null;
}) {
  if (!change) return null;
  const kind = KIND_LABEL[change.kind ?? ""] ?? "dokument";
  const text =
    change.rate !== null && change.rate !== undefined
      ? `${kind}: ${ratePl(change.rate)} od ${monthPl(change.from)}`
      : `${kind}: inna stawka od ${monthPl(change.from)}`;
  return (
    <span
      data-testid="rate-document-row-note"
      title="Umowa albo aneks w Dokumentach podaje stawkę, której nie ma w kontrakcie"
      className="mt-0.5 inline-block max-w-full truncate rounded border border-warning/40 bg-warning-muted px-1.5 text-[11px] font-medium leading-4 text-warning-muted-foreground"
    >
      {change.count > 1 ? `${text} (+${change.count - 1})` : text}
    </span>
  );
}
