"use client";

/**
 * „Po osobach, które odeszły” w „Czeka na Ciebie” (decyzja Artura 28.10.2026).
 *
 * Gdy konto rekrutera zostaje wyłączone, jego żywe pary domyka Delivery Lead
 * rekrutacji (`services/departure_care.py`). Kafel mówi DL-owi, po kim i ile
 * zostało, od najbliższych klienta; „Otwórz listę” prowadzi do
 * `/departed-care`. Head of Recruitment widzi tu też DL-i z parami
 * niedomkniętymi dłużej niż 10 dni roboczych.
 */

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { shortDate } from "@/lib/candidate-followup";
import {
  CARE_COLUMN_LABELS,
  CARE_LINK,
  columnCounts,
  jobsPhrase,
  peoplePhrase,
  shortName,
  type DepartedCareResponse,
} from "@/lib/departed-care";

import { Section } from "./BoardTasksSection";

/** Ile pozycji kafel dokłada do „Twój ruch”. */
export function departedCareCount(data: DepartedCareResponse | null | undefined): number {
  // Starszy serwer (albo inna odpowiedź) pól nie ma — wtedy kafla nie ma.
  return (data?.groups?.length ?? 0) + (data?.overdue?.length ?? 0);
}

export function DepartedCareSection({
  data,
  failed,
  expanded,
  onToggle,
}: {
  data: DepartedCareResponse | null | undefined;
  failed: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (failed) {
    return (
      <section aria-label="Po osobach, które odeszły" className="min-w-0">
        <h3 className="mb-2 text-sm font-semibold">Po osobach, które odeszły</h3>
        <p role="alert" className="text-xs text-destructive">
          Nie udało się sprawdzić, czy czekają na Ciebie kandydaci po osobach, które odeszły.
        </p>
      </section>
    );
  }
  if (!data || departedCareCount(data) === 0) return null;
  const groups = expanded ? data.groups : data.groups.slice(0, 3);

  return (
    <Section
      title="Po osobach, które odeszły"
      hint="Konto rekrutera jest wyłączone, a jego kandydaci w Twoich rekrutacjach są do domknięcia przez Ciebie. Zacznij od najbliższych klienta."
      count={data.total || data.overdue.length}
      rows={data.groups.length}
      expanded={expanded}
      onToggle={onToggle}
    >
      {groups.map((group) => (
        <li key={group.departed_user_id} className="space-y-1.5 px-3 py-2" data-testid="departed-care-group">
          <div className="flex items-baseline justify-between gap-2">
            <p className="min-w-0 truncate text-sm font-medium">{shortName(group.departed_name)}</p>
            <span className="shrink-0 text-xs font-semibold tabular-nums">
              {peoplePhrase(group.pairs)}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            konto wyłączone · przejęte {shortDate(group.since)} · {jobsPhrase(group.jobs)}
          </p>
          {group.clients.length > 0 ? (
            <p className="truncate text-xs text-muted-foreground" title={group.clients.join(", ")}>
              {group.clients.join(", ")}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-1">
            {columnCounts(group.columns).map(([column, count]) => (
              <span
                key={column}
                className="rounded-full bg-muted px-2 py-0.5 text-[11px] tabular-nums text-muted-foreground"
              >
                {count} {CARE_COLUMN_LABELS[column]}
              </span>
            ))}
            <Button size="sm" variant="quiet" className="ml-auto" asChild>
              <Link href={`${CARE_LINK}?from=${group.departed_user_id}`}>Otwórz listę</Link>
            </Button>
          </div>
        </li>
      ))}
      {data.overdue.map((row) => (
        <li key={`overdue-${row.user_id}`} className="px-3 py-2" data-testid="departed-care-overdue">
          <p className="text-sm">
            <span className="font-medium">{row.name}</span> — {peoplePhrase(row.pairs)} niedomkniętych
            ponad {data.escalate_after_days} dni roboczych
          </p>
          <p className="truncate text-xs text-muted-foreground">
            po: {row.departed.map(shortName).join(", ")} · od {shortDate(row.since)}
          </p>
        </li>
      ))}
    </Section>
  );
}
