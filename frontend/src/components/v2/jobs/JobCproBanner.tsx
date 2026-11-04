"use client";

import { Mail } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { CproJobEvents } from "@/lib/cpro-events-api";
import { formatDayMonthPl } from "@/lib/date-pl";

const HOUR = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function dayHour(iso: string): string {
  return `${formatDayMonthPl(iso)} o ${HOUR.format(new Date(iso))}`;
}

function recruitersLabel(count: number): string {
  return count === 1 ? "1 rekruterowi" : `${count} rekruterom`;
}

function peopleLabel(count: number): string {
  if (count === 1) return "1 osobę";
  if (count >= 2 && count <= 4) return `${count} osoby`;
  return `${count} osób`;
}

export interface JobCproBannerProps {
  jobId: number;
  events: CproJobEvents | null | undefined;
  onChangeReason?: () => void;
  onReopen?: () => void;
}

/** Co NEXUS zrobił sam z maili CPro w tej rekrutacji (02.11.2026). */
export function JobCproBanner({ jobId, events, onChangeReason, onReopen }: JobCproBannerProps) {
  if (!events) return null;
  const { closed, rejected, rejected_more: rejectedMore } = events;
  if (!closed && rejected.length === 0) return null;
  const total = rejected.length + rejectedMore;
  return (
    <div className="mb-3 space-y-2" data-testid="job-cpro-banner">
      {closed ? (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted px-4 py-2.5 text-sm"
        >
          <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="min-w-0 flex-1 text-foreground">
            <strong>Zamknięte z CPro {dayHour(closed.at)}.</strong> Nordea zamknęła request {closed.request}
            {closed.cpro_reason ? ` (powód w CPro: ${closed.cpro_reason})` : ""}. NEXUS wpisał „{closed.nexus_reason}”
            {closed.notified > 0 ? ` i dał znać ${recruitersLabel(closed.notified)}` : ""}.
          </p>
          {onChangeReason ? (
            <Button type="button" size="sm" variant="outline" onClick={onChangeReason}>
              Zmień powód
            </Button>
          ) : null}
          {onReopen ? (
            <Button type="button" size="sm" variant="outline" onClick={onReopen}>
              Otwórz ponownie
            </Button>
          ) : null}
        </div>
      ) : null}
      {rejected.length > 0 ? (
        <div role="status" className="rounded-lg border border-border bg-muted px-4 py-2.5 text-sm">
          <p className="flex items-center gap-2 text-foreground">
            <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <strong>Z CPro: klient odrzucił {peopleLabel(total)}. NEXUS przeniósł karty do „Zamknięci”.</strong>
          </p>
          <ul className="mt-1.5 space-y-1">
            {rejected.map((row) => (
              <li key={`${row.candidate_id}-${row.at}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-6">
                <span className="font-medium text-foreground">{row.person}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {row.reason ? `„${row.reason}” · ` : ""}
                  {dayHour(row.at)}
                </span>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/jobs/${jobId}?candidate=${row.candidate_id}`}>Napisz do kandydata</Link>
                </Button>
              </li>
            ))}
          </ul>
          {rejectedMore > 0 ? (
            <p className="mt-1 pl-6 text-muted-foreground">I jeszcze {rejectedMore} w kolumnie „Zamknięci”.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
