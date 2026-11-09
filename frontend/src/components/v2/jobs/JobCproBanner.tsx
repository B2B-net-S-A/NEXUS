"use client";

import { useEffect, useState } from "react";
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

/** Po tylu dniach od najnowszego zdarzenia CPro baner sam znika (U3, 08.11.2026). */
const HIDE_AFTER_MS = 7 * 86_400_000;

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

function newestEventAt(events: CproJobEvents): string | null {
  const dates = [events.closed?.at, ...events.rejected.map((row) => row.at)].filter(
    (at): at is string => Boolean(at),
  );
  return dates.length ? dates.reduce((a, b) => (Date.parse(a) > Date.parse(b) ? a : b)) : null;
}

const seenKey = (jobId: number) => `nexus:cpro-banner-seen:${jobId}`;

/** Co ten użytkownik już obejrzał; bez pamięci przeglądarki baner po prostu wraca. */
function readSeen(jobId: number): string | null {
  try {
    return window.localStorage.getItem(seenKey(jobId));
  } catch {
    return null;
  }
}

function writeSeen(jobId: number, at: string): void {
  try {
    window.localStorage.setItem(seenKey(jobId), at);
  } catch {
    // Prywatne okno: baner wróci przy następnym wejściu, nic więcej się nie psuje.
  }
}

export interface JobCproBannerProps {
  jobId: number;
  events: CproJobEvents | null | undefined;
  onChangeReason?: () => void;
  onReopen?: () => void;
}

/**
 * Co NEXUS zrobił sam z maili CPro w tej rekrutacji (02.11.2026). Od audytu U3
 * (08.11.2026) jedna linia z „Pokaż”: trzy wiersze „Napisz do kandydata”
 * zjadały u Delivery Leada cały rząd kart. Po otwarciu albo po 7 dniach znika;
 * „Zmień powód” i „Otwórz ponownie” zostają też w menu „⋯” nagłówka.
 */
export function JobCproBanner({ jobId, events, onChangeReason, onReopen }: JobCproBannerProps) {
  const [open, setOpen] = useState(false);
  // `undefined` = jeszcze nie przeczytano pamięci przeglądarki (render na serwerze).
  const [seenAt, setSeenAt] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    setSeenAt(readSeen(jobId));
  }, [jobId]);

  if (!events || seenAt === undefined) return null;
  const { closed, rejected, rejected_more: rejectedMore } = events;
  if (!closed && rejected.length === 0) return null;
  const newest = newestEventAt(events);
  if (!newest) return null;
  if (!open) {
    if (Date.now() - Date.parse(newest) > HIDE_AFTER_MS) return null;
    if (seenAt && Date.parse(seenAt) >= Date.parse(newest)) return null;
  }

  const total = rejected.length + rejectedMore;
  const summary = closed
    ? `Zamknięte z CPro ${dayHour(closed.at)}`
    : `Z CPro: klient odrzucił ${peopleLabel(total)}`;

  if (!open) {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-1 text-[13px]" data-testid="job-cpro-banner">
        <Mail className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <p className="min-w-0 truncate text-foreground">
          <strong>{summary}</strong>
        </p>
        <button
          type="button"
          data-testid="job-cpro-banner-show"
          onClick={() => {
            setOpen(true);
            writeSeen(jobId, newest);
          }}
          className="shrink-0 font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Pokaż
        </button>
      </div>
    );
  }

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
