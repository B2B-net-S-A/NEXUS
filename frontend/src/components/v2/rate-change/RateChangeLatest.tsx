"use client";

import { rateChangeStatusLabel, useRateChanges } from "@/lib/rate-change";

function dateLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: "Europe/Warsaw" });
}

/**
 * Ostatnia zmiana stawki kandydata w tej rekrutacji (0418) — pod stawkami na
 * profilu: kiedy, było → jest, stan sprawy, kto i skąd. Bez zmian nic nie
 * renderuje (brak wpisu to nie informacja).
 */
export function RateChangeLatest({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const view = useRateChanges(candidateId, jobId);
  const latest = view.data?.changes.find((c) => c.status !== "superseded") ?? null;
  if (!latest) return null;
  const parts = [
    `Zmiana stawki ${dateLabel(latest.created_at)}:`,
    latest.previous ? `${latest.previous.label} → ${latest.requested.label}` : latest.requested.label,
  ];
  const meta = [
    latest.status !== "noted" ? rateChangeStatusLabel(latest.status) : null,
    latest.agreed ? `ustalona ${latest.agreed.label}` : null,
    [latest.created_by_name, latest.source_label].filter(Boolean).join(", ") || null,
  ].filter(Boolean);
  return (
    <p className="mt-2 text-xs text-muted-foreground" data-testid="rate-change-latest">
      <span className="font-medium text-foreground">{parts.join(" ")}</span>
      {meta.length ? ` · ${meta.join(" · ")}` : ""}
      {latest.note ? <span className="block break-words">„{latest.note}”</span> : null}
    </p>
  );
}
