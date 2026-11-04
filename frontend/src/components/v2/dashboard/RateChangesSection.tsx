"use client";

/**
 * „Zmiany stawki” w „Czeka na Ciebie” (0418, D3 i D6).
 *
 * Wiersze z `GET /api/board-tasks`:
 *  - `rate_changes` („Twój ruch”): Delivery Lead decyduje o stawce do klienta
 *    po wzroście stawki kandydata z CV u klienta; osoba wskazana do negocjacji
 *    rozmawia z kandydatem,
 *  - `rate_changes_by_others` („U innych”): Twoje zgłoszenie czeka na DL albo
 *    negocjatora; Head of Recruitment widzi sprawy czekające > 2 dni robocze.
 * Akcje są w panelu osoby na Tablicy (`RateChangeBanner`) — link otwiera go.
 */

import Link from "next/link";
import { useState } from "react";
import { Clock } from "lucide-react";

import { waitingFor } from "@/lib/api/boardTasks";
import { rateTaskLine, type RateChangeTaskRow } from "@/lib/rate-change";

const ROWS = 5;

const REASON_LABEL: Record<RateChangeTaskRow["reason"], string> = {
  decide: "Zdecyduj o stawce do klienta",
  negotiate: "Porozmawiaj z kandydatem o stawce",
  waiting: "Czeka",
};

function dayMonth(iso: string): string {
  const [, m, d] = iso.split("-");
  return d && m ? `${d}.${m}` : iso;
}

function personLink(row: RateChangeTaskRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function RateList({
  title,
  hint,
  rows,
  testId,
}: {
  title: string;
  hint: string;
  rows: RateChangeTaskRow[];
  testId: string;
}) {
  const [all, setAll] = useState(false);
  if (rows.length === 0) return null;
  const shown = all ? rows : rows.slice(0, ROWS);
  return (
    <section aria-label={title} className="min-w-0" data-testid={testId}>
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {rows.length}
        </span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">{hint}</p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => (
          <li key={row.change_id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
            <div className="min-w-[12rem] flex-1">
              <Link
                href={personLink(row)}
                title={row.candidate_name}
                className="block max-w-full truncate text-sm font-medium hover:underline"
              >
                {row.candidate_name}
              </Link>
              <p className="truncate text-xs text-muted-foreground">
                {row.job_title}
                {row.client_name ? ` · ${row.client_name}` : ""}
              </p>
              <p className="text-xs tabular-nums text-muted-foreground">
                {rateTaskLine(row)}
                {row.reason === "waiting" && row.waiting_on ? ` · czeka na: ${row.waiting_on}` : ""}
                {row.reason !== "waiting" ? ` · ${REASON_LABEL[row.reason]}` : ""}
                {row.negotiation_due ? ` · do ${dayMonth(row.negotiation_due)}` : ""}
              </p>
            </div>
            <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-xs tabular-nums text-muted-foreground">
              <Clock className="h-3 w-3" aria-hidden />
              {waitingFor(row.since)}
            </span>
          </li>
        ))}
      </ul>
      {rows.length > ROWS ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {all ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      ) : null}
    </section>
  );
}

export function RateChangesSection({ rows }: { rows: RateChangeTaskRow[] | null | undefined }) {
  return (
    <RateList
      title="Zmiany stawki kandydata"
      hint="Kandydat chce innej stawki, a CV jest u klienta — zdecyduj o stawce do klienta albo porozmawiaj z kandydatem."
      rows={rows ?? []}
      testId="rate-changes-mine"
    />
  );
}

export function RateChangesWaitingSection({ rows }: { rows: RateChangeTaskRow[] | null | undefined }) {
  return (
    <RateList
      title="Zmiany stawki w toku"
      hint="Zgłoszona zmiana stawki czeka na decyzję DL albo wynik negocjacji."
      rows={rows ?? []}
      testId="rate-changes-others"
    />
  );
}
