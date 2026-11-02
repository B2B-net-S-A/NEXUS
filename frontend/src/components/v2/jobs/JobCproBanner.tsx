"use client";

import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatDayMonthPl } from "@/lib/date-pl";
import type { CproJobEvents } from "@/lib/cpro-events-api";

const HOUR = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function dayHour(iso: string): string {
  return `${formatDayMonthPl(iso)} o ${HOUR.format(new Date(iso))}`;
}

function recruitersLabel(count: number): string {
  if (count === 1) return "1 rekruterowi";
  return `${count} rekruterom`;
}

function peopleLabel(count: number): string {
  if (count === 1) return "1 osobę";
  if (count >= 2 && count <= 4) return `${count} osoby`;
  return `${count} osób`;
}

/** PROTOTYP do makiety: co NEXUS zrobił sam z maila CPro w tej rekrutacji. */
export function JobCproBanner({ events }: { events: CproJobEvents | null | undefined }) {
  if (!events) return null;
  const { closed, rejected } = events;
  if (!closed && rejected.length === 0) return null;
  return (
    <div className="mb-3 space-y-2" data-testid="job-cpro-banner">
      {closed ? (
        <div
          role="status"
          className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted px-4 py-2.5 text-sm"
        >
          <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="min-w-0 flex-1 text-foreground">
            <strong>Zamknięte z CPro {dayHour(closed.at)}.</strong> Nordea zamknęła request {closed.request} (powód
            w CPro: {closed.cpro_reason}). NEXUS wpisał „{closed.nexus_reason}” i dał znać{" "}
            {recruitersLabel(closed.notified)}.
          </p>
          <Button type="button" size="sm" variant="outline">
            Zobacz mail
          </Button>
          <Button type="button" size="sm" variant="outline">
            Zmień powód
          </Button>
          <Button type="button" size="sm" variant="outline">
            Otwórz ponownie
          </Button>
        </div>
      ) : null}
      {rejected.length > 0 ? (
        <div role="status" className="rounded-lg border border-border bg-muted px-4 py-2.5 text-sm">
          <p className="flex items-center gap-2 text-foreground">
            <Mail className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <strong>
              Z CPro: klient odrzucił {peopleLabel(rejected.length)}. NEXUS przeniósł karty do „Zamknięci”.
            </strong>
          </p>
          <ul className="mt-1.5 space-y-1">
            {rejected.map((row) => (
              <li key={row.candidate_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-6">
                <span className="font-medium text-foreground">{row.person}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  „{row.reason}” · {dayHour(row.at)}
                </span>
                <Button type="button" size="sm" variant="outline">
                  Napisz do kandydata
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
