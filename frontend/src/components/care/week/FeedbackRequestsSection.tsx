"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ClientFeedbackDialog } from "@/components/care/ClientFeedbackDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { WeekFeedback } from "@/lib/api/care";
import { REASON_LABELS, formatAverage } from "@/lib/api/client-people";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl } from "@/lib/date-pl";

import { feedbackDueText, shortNames } from "./week-format";

/** Ostatnia data końca wśród konsultantów menedżera („zamówienia do 30.11”). */
function endsText(item: WeekFeedback): string | null {
  const ends = item.consultants
    .map((c) => c.end_date)
    .filter((d): d is string => Boolean(d))
    .sort();
  if (!ends.length) return null;
  const label = item.consultants.length > 1 ? "zamówienia do" : "zamówienie do";
  return `${label} ${formatDayMonthPl(ends[ends.length - 1])}`;
}

/**
 * „Opinie od menedżerów u klientów” — pas pod planem tygodnia, jedna pozycja
 * na menedżera ze wszystkimi jego konsultantami (D9) i terminem. „Zapisz
 * opinię” otwiera to samo okno co „Struktura u klienta”.
 */
export function FeedbackRequestsSection({
  items,
  canWrite,
  today,
}: {
  items: WeekFeedback[];
  canWrite: boolean;
  today: string;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<WeekFeedback | null>(null);
  if (!items.length) return null;
  return (
    <section
      className="overflow-hidden rounded-lg border border-border bg-card"
      aria-labelledby="care-week-feedback"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <h3 id="care-week-feedback" className="flex items-center gap-2 text-sm font-semibold">
          Opinie od menedżerów u klientów
          <Badge size="sm" variant="neutral">
            {items.length}
          </Badge>
        </h3>
        <span className="text-xs text-muted-foreground">
          przed końcem zamówienia i raz na kwartał
        </span>
      </div>
      <ul>
        {items.map((item) => {
          const ends = endsText(item);
          const due = feedbackDueText(item.due_on, today);
          return (
            <li
              key={item.contact_id}
              className="grid grid-cols-1 items-center gap-x-3 gap-y-1 border-t border-border/60 px-4 py-2.5 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1.6fr)_auto_auto]"
            >
              <div className="min-w-0">
                <span className="font-medium">{item.contact_name}</span>
                <span className={CALM_SUBLINE}>
                  {[item.client_name, item.area?.name, item.position].filter(Boolean).join(" · ")}
                </span>
              </div>
              <div className="min-w-0 text-sm">
                o: <span className="font-semibold">{shortNames(item.consultants.map((c) => c.candidate_name))}</span>
                <span className={CALM_SUBLINE}>
                  {[
                    ends,
                    item.reasons.map((r) => REASON_LABELS[r]).join(", "),
                    item.last_feedback
                      ? `ostatnio ${formatDayMonthPl(item.last_feedback.held_on)} · ${formatAverage(item.last_feedback.average)}`
                      : "bez opinii",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
              <Badge variant={due.overdue ? "warning" : "neutral"} className="justify-self-start">
                {due.text}
              </Badge>
              <div className="sm:text-right">
                {canWrite ? (
                  <Button
                    size="sm"
                    variant={due.overdue ? "primary" : "outline"}
                    onClick={() => setOpen(item)}
                  >
                    Zapisz opinię
                  </Button>
                ) : null}
              </div>
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
