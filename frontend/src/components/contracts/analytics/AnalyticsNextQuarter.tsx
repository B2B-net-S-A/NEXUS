"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { UseQueryResult } from "@tanstack/react-query";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CALM_SUBLINE } from "@/lib/calm-table";
import {
  daysBetweenIso,
  endingDecisionLine,
  endingNote,
  sortWindow,
  summarizeWindow,
  windowGapNote,
  windowMarginGap,
  windowMonthlyMargin,
  type WindowContract,
} from "@/lib/contract-analytics";
import { relativeDays } from "@/lib/contract-happening";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatWholeMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

/** Strona listy `/api/contracts` (serwer oddaje do 100 pozycji). */
export interface WindowPage {
  items?: WindowContract[];
  total?: number;
}

export type WindowQuery = UseQueryResult<WindowPage>;

const SHOWN = 5;

function people(n: number): string {
  return countPl(n, "osoba", "osoby", "osób");
}

/** „+47 321 zł” / „−75 432 zł” — znak mówi, czy marża przybywa, czy ubywa. */
function signedMargin(value: number, kind: "ending" | "starting"): string {
  return formatWholeMoney(kind === "ending" ? -value : value, "PLN", true);
}

/** Zdanie przy błędzie okna: brak uprawnienia do listy to nie awaria. */
export function windowErrorText(error: unknown): string {
  return isForbiddenError(error)
    ? "Lista kontraktów wymaga uprawnienia „Klienci, kontrakty i zamówienia: podgląd”."
    : "Nie udało się pobrać listy kontraktów.";
}

function WindowRow({ c, kind, today }: { c: WindowContract; kind: "ending" | "starting"; today: string }) {
  const date = kind === "ending" ? c.end_date : c.start_date;
  const margin = windowMonthlyMargin(c);
  const gap = windowMarginGap(c);
  const note =
    kind === "ending"
      ? endingNote(c)
      : gap === "no_rates"
        ? "brak stawek w kontrakcie"
        : gap === "other_currency"
          ? "stawki w innej walucie"
          : null;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_96px_88px] items-center gap-3 py-2">
      <div className="min-w-0">
        <Link
          href={`/contracts/${c.id}`}
          className="text-[13px] font-medium text-foreground hover:text-primary hover:underline"
        >
          {c.candidate_name ?? "—"}
        </Link>
        <span className={cn(CALM_SUBLINE, "truncate")} title={c.client_name ?? undefined}>
          {c.client_name}
          {note ? ` · ${note}` : ""}
        </span>
      </div>
      <span className="text-right text-[12.5px] tabular-nums text-muted-foreground">
        {margin == null ? "—" : signedMargin(margin, kind)}
      </span>
      <span className="text-right">
        <span className="block text-[12.5px] tabular-nums text-foreground">{formatIsoDatePl(date)}</span>
        {date ? (
          <span className="block text-[11.5px] text-muted-foreground">
            {relativeDays(daysBetweenIso(today, date))}
          </span>
        ) : null}
      </span>
    </li>
  );
}

function WindowCard({ kind, query, today }: { kind: "ending" | "starting"; query: WindowQuery; today: string }) {
  const [all, setAll] = useState(false);
  const items = useMemo(
    () => sortWindow(query.data?.items ?? [], kind === "ending" ? "end_date" : "start_date"),
    [query.data, kind],
  );
  const summary = summarizeWindow(items);
  const gapNote = windowGapNote(summary);
  const Icon = kind === "ending" ? TrendingDown : TrendingUp;
  const shown = all ? items : items.slice(0, SHOWN);
  const total = query.data?.total ?? items.length;
  const subline =
    kind === "ending"
      ? [endingDecisionLine(items), gapNote].filter(Boolean).join(" · ")
      : (gapNote ?? "Wszystkie mają stawki klienta i konsultanta");

  return (
    <section className="flex min-w-0 flex-col rounded-xl border border-border bg-card shadow-xs">
      <div className="border-b border-border/60 px-4 py-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="flex items-center gap-1.5 self-center text-[13.5px] font-semibold text-foreground">
            <Icon className={cn("size-4", kind === "ending" ? "text-warning" : "text-success")} aria-hidden />
            {kind === "ending" ? "Kończą się" : "Startują"}
          </h3>
          {query.isSuccess ? (
            <p className="text-right">
              <span className="font-display text-[20px] font-semibold leading-7 tabular-nums text-foreground">
                {people(summary.people)}
              </span>
              <span className="ml-2 whitespace-nowrap text-[12.5px] tabular-nums text-muted-foreground">
                {items.length ? `${signedMargin(summary.margin, kind)} marży / mies.` : "bez zmian w marży"}
              </span>
            </p>
          ) : null}
        </div>
        {query.isSuccess && items.length > 0 && subline ? (
          <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{subline}</p>
        ) : null}
      </div>
      {query.isError ? (
        <div className="flex flex-wrap items-center gap-x-2 px-4 py-5 text-[13px]">
          <span className={isForbiddenError(query.error) ? "text-muted-foreground" : "text-destructive"}>
            {windowErrorText(query.error)}
          </span>
          {isForbiddenError(query.error) ? null : (
            <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => void query.refetch()}>
              Ponów
            </Button>
          )}
        </div>
      ) : !query.isSuccess ? (
        <p className="px-4 py-5 text-[13px] text-muted-foreground">Ładowanie…</p>
      ) : items.length === 0 ? (
        <p className="px-4 py-5 text-[13px] text-muted-foreground">
          {kind === "ending"
            ? "Nikomu nie kończy się umowa w najbliższych 90 dniach."
            : "W najbliższych 90 dniach nie startuje żadna umowa."}
        </p>
      ) : (
        <>
          <ul className="flex-1 divide-y divide-border/60 px-4">
            {shown.map((c) => (
              <WindowRow key={c.id} c={c} kind={kind} today={today} />
            ))}
          </ul>
          {items.length > SHOWN || total > items.length ? (
            <div className="flex flex-wrap items-center gap-x-3 border-t border-border/60 px-4 py-1.5">
              {items.length > SHOWN ? (
                <Button type="button" variant="tertiary" size="sm" className="px-0" onClick={() => setAll((v) => !v)}>
                  {all ? `Pokaż ${SHOWN} najbliższych` : `Pokaż wszystkie (${items.length})`}
                </Button>
              ) : null}
              {total > items.length ? (
                <span className="text-[12px] text-muted-foreground">
                  Pokazano {items.length} z {total} — sumy liczą tylko pokazane.
                </span>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * „Najbliższe 3 miesiące” (wariant A): kto kończy, kto startuje i ile marży
 * miesięcznej to zabiera albo dodaje — z bieżących stawek kontraktów, tylko
 * kwoty w PLN.
 */
export function AnalyticsNextQuarter({
  ending,
  starting,
  today,
  until,
}: {
  ending: WindowQuery;
  starting: WindowQuery;
  today: string;
  until: string;
}) {
  const lost = summarizeWindow(ending.data?.items ?? []).margin;
  const gained = summarizeWindow(starting.data?.items ?? []).margin;
  const ready = ending.isSuccess && starting.isSuccess;
  return (
    <section aria-label="Najbliższe 3 miesiące" data-tour="contracts.analytics.next90" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-[14px] font-semibold text-foreground">
          Najbliższe 3 miesiące{" "}
          <span className="font-normal text-muted-foreground">· do {formatIsoDatePl(until)}</span>
        </h2>
        {ready ? (
          <p className="text-[12.5px] text-muted-foreground">
            Bilans marży:{" "}
            <span className="font-semibold tabular-nums text-foreground">
              {formatWholeMoney(gained - lost, "PLN", true)} / mies.
            </span>{" "}
            (z bieżących stawek kontraktów)
          </p>
        ) : null}
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <WindowCard kind="ending" query={ending} today={today} />
        <WindowCard kind="starting" query={starting} today={today} />
      </div>
    </section>
  );
}
