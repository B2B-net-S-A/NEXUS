"use client";

/**
 * Ramka off-limits w panelu osoby (21.10.2026): osoba pracuje w firmie,
 * z której nie wyciągamy ludzi, a do rekrutacji weszła po potwierdzeniu
 * „sam(a) się zgłosił(a)”. Pokazuje, kto, kiedy i jak potwierdził — gdyby
 * klient zapytał, odpowiedź jest tutaj.
 */

import { Ban } from "lucide-react";

import { offLimitsConfirmedDay, type OffLimitsBadge } from "@/lib/off-limits";

export function offLimitsNoticeText(badge: OffLimitsBadge): string {
  const day = offLimitsConfirmedDay(badge.confirmed_at);
  const who = [badge.confirmed_by_name, day].filter(Boolean).join(", ");
  const how =
    badge.how === "left_company" ? "Już tam nie pracuje" : `Sam(a) się zgłosił(a): „${badge.how_label}”`;
  return `${how}${who ? ` — potwierdził(a) ${who}` : ""}.`;
}

export function PersonOffLimits({ badge }: { badge: OffLimitsBadge | null | undefined }) {
  if (!badge) return null;
  return (
    <div
      data-testid="person-off-limits"
      className="flex gap-2.5 rounded-lg border border-warning/40 bg-warning-muted px-3 py-2.5 text-[13px] text-warning-muted-foreground"
    >
      <Ban className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p>
        <strong>{badge.client_name} — stamtąd nie wyciągamy ludzi.</strong>{" "}
        {offLimitsNoticeText(badge)}
      </p>
    </div>
  );
}
