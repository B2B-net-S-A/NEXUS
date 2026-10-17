"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ClientFeedbackDialog } from "@/components/care/ClientFeedbackDialog";
import { Button } from "@/components/ui/button";
import type { WeekFeedback } from "@/lib/api/care";
import { REASON_LABELS, formatAverage } from "@/lib/api/client-people";
import { CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { dayMonth, shortNames } from "./week-format";

/** Ostatnia data końca wśród konsultantów menedżera („zamówienia do 30.11”). */
function endsText(item: WeekFeedback): string | null {
  const ends = item.consultants
    .map((c) => c.end_date)
    .filter((d): d is string => Boolean(d))
    .sort();
  if (!ends.length) return null;
  const label = item.consultants.length > 1 ? "zamówienia do" : "zamówienie do";
  return `${label} ${dayMonth(ends[ends.length - 1])}`;
}

/**
 * „Opinia od menedżera u klienta” — jedna pozycja na menedżera ze wszystkimi
 * jego konsultantami (D9). „Zapisz opinię” otwiera to samo okno co
 * „Struktura u klienta”.
 */
export function FeedbackRequestsSection({
  items,
  canWrite,
}: {
  items: WeekFeedback[];
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<WeekFeedback | null>(null);
  if (!items.length) return null;
  return (
    <section className="space-y-1.5" aria-labelledby="care-week-feedback">
      <h3
        id="care-week-feedback"
        className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Opinia od menedżera u klienta
      </h3>
      <ul className="rounded-lg border border-border bg-card">
        {items.map((item) => {
          const ends = endsText(item);
          return (
            <li
              key={item.contact_id}
              className={cn(CALM_ROW, "flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2")}
            >
              <div className="min-w-0 flex-1">
                <span className="font-medium">{item.contact_name}</span>
                <span className={CALM_SUBLINE}>
                  {[item.client_name, item.area?.name, item.position].filter(Boolean).join(" · ")}
                </span>
              </div>
              <div className="min-w-0 flex-1 text-sm">
                {shortNames(item.consultants.map((c) => c.candidate_name))}
                <span className={CALM_SUBLINE}>
                  {[
                    ends,
                    item.reasons.map((r) => REASON_LABELS[r]).join(", "),
                    item.overdue ? `czeka od ${dayMonth(item.due_on)}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              <div className="w-36 text-sm tabular-nums text-muted-foreground">
                {item.last_feedback
                  ? `ostatnio ${dayMonth(item.last_feedback.held_on)} · ${formatAverage(item.last_feedback.average)}`
                  : "bez opinii"}
              </div>
              {canWrite ? (
                <Button size="sm" variant="outline" onClick={() => setOpen(item)}>
                  Zapisz opinię
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {open ? (
        <ClientFeedbackDialog
          clientId={open.client_id}
          clientName={open.client_name}
          manager={{ id: open.contact_id, name: open.contact_name }}
          consultants={open.consultants}
          open
          onOpenChange={(next) => {
            if (next) return;
            setOpen(null);
            // Okno opinii odświeża strukturę klienta; kolejka tygodnia — tu.
            void queryClient.invalidateQueries({ queryKey: ["care", "week"] });
          }}
        />
      ) : null}
    </section>
  );
}
