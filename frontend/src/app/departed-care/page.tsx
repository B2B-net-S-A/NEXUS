"use client";

/**
 * „Po osobach, które odeszły” — lista do domknięcia dla Delivery Leada
 * (decyzje Artura 28.10.2026, backend `services/departure_care.py`).
 *
 * Gdy konto rekrutera zostaje wyłączone, jego żywe pary w Twoich
 * rekrutacjach domykasz Ty: doprowadzasz do końca albo odrzucasz z powodem.
 * Ruch karty i odrzucenie idą zwykłą drogą Tablicy (panel osoby, zaznaczenie
 * wielu kart) — tu tylko lista od najbliższych klienta i linki.
 * `?from=<id>` (link z maila) pokazuje jedną osobę, która odeszła.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/ds/PageHeader";
import { Button } from "@/components/ui/button";
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState";
import { shortDate } from "@/lib/candidate-followup";
import {
  CARE_COLUMN_LABELS,
  CARE_LINK,
  columnCounts,
  jobsPhrase,
  peoplePhrase,
  shortName,
  useDepartedCare,
  type DepartedCareGroup,
  type DepartedCareRow,
} from "@/lib/departed-care";

const ENTRY_COLUMNS = new Set(["new", "screening"]);

function jobsOf(rows: DepartedCareRow[]): Array<{ id: number; title: string; entry: number }> {
  const jobs = new Map<number, { id: number; title: string; entry: number }>();
  for (const row of rows) {
    const job = jobs.get(row.job_id) ?? { id: row.job_id, title: row.job_title, entry: 0 };
    if (ENTRY_COLUMNS.has(row.column)) job.entry += 1;
    jobs.set(row.job_id, job);
  }
  return Array.from(jobs.values()).filter((j) => j.entry > 0);
}

function GroupCard({ group }: { group: DepartedCareGroup }) {
  const entryJobs = jobsOf(group.rows);
  return (
    <section
      aria-label={`Po ${shortName(group.departed_name)}`}
      className="rounded-xl border border-border bg-card"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">
            {shortName(group.departed_name)}{" "}
            <span className="text-sm font-normal text-muted-foreground">
              · konto wyłączone · przejęte {shortDate(group.since)}
            </span>
          </h2>
          <p className="text-xs text-muted-foreground">
            {[group.clients.join(", "), jobsPhrase(group.jobs)].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className="text-sm font-semibold tabular-nums">
          {peoplePhrase(group.pairs)} do domknięcia
        </span>
      </header>
      <div className="flex flex-wrap gap-1 px-4 pt-3">
        {columnCounts(group.columns).map(([column, count]) => (
          <span
            key={column}
            className="rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground"
          >
            {count} {CARE_COLUMN_LABELS[column]}
          </span>
        ))}
      </div>
      <ul className="divide-y divide-border px-1 py-2">
        {group.rows.map((row) => (
          <li
            key={`${row.job_id}-${row.candidate_id}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
            data-testid="departed-care-row"
          >
            <div className="min-w-[12rem] flex-1">
              <Link
                href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}
                className="block truncate text-sm font-medium hover:underline"
              >
                {row.candidate_name}
              </Link>
              <p className="truncate text-xs text-muted-foreground">
                {row.job_title}
                {row.client_name ? ` · ${row.client_name}` : ""}
              </p>
            </div>
            <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs text-foreground">
              {CARE_COLUMN_LABELS[row.column]}
            </span>
            <span className="w-24 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
              {row.moved_at ? `ruch ${shortDate(row.moved_at)}` : ""}
            </span>
            <Button size="sm" variant="quiet" asChild>
              <Link href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}>Otwórz</Link>
            </Button>
          </li>
        ))}
      </ul>
      {entryJobs.length > 0 ? (
        <footer className="space-y-1 border-t border-border px-4 py-3 text-xs text-muted-foreground">
          <p>
            Stare karty w „Nowych” i „Screeningu” odrzucisz naraz na Tablicy: filtr „Po osobach,
            które odeszły”, zaznacz karty i „Odrzuć” z powodem.
          </p>
          <p className="flex flex-wrap gap-x-3 gap-y-1">
            {entryJobs.map((job) => (
              <Link
                key={job.id}
                href={`/jobs/${job.id}?added_by=departed`}
                className="font-medium text-primary hover:underline"
              >
                {job.title} · {peoplePhrase(job.entry)} na wejściu
              </Link>
            ))}
          </p>
        </footer>
      ) : null}
    </section>
  );
}

function DepartedCareScreen() {
  const params = useSearchParams();
  const from = Number(params?.get("from") ?? "") || null;
  const query = useDepartedCare();
  const groups = (query.data?.groups ?? []).filter(
    (g) => from == null || g.departed_user_id === from,
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Po osobach, które odeszły"
        description="Kandydaci rekruterów z wyłączonym kontem w Twoich rekrutacjach. Doprowadź ich do końca albo odrzuć z powodem — to nie liczy się do Ligi, KPI ani premii."
        density="compact"
        actions={
          from != null ? (
            <Button size="sm" variant="outline" asChild>
              <Link href={CARE_LINK}>Wszystkie osoby</Link>
            </Button>
          ) : null
        }
      />
      {query.isError ? (
        <div className="rounded-xl border border-border bg-card px-4">
          <WidgetErrorBlock
            title="Nie udało się wczytać listy po osobach, które odeszły."
            error={query.error}
            onRetry={() => void query.refetch()}
          />
        </div>
      ) : query.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : query.isSuccess && groups.length === 0 ? (
        <p role="status" className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          {from != null
            ? "Po tej osobie nic już nie czeka — wszystko domknięte."
            : "Nic nie czeka. Kandydaci po osobach, które odeszły, są domknięci."}
        </p>
      ) : (
        groups.map((group) => <GroupCard key={group.departed_user_id} group={group} />)
      )}
      {query.isSuccess && (query.data?.overdue.length ?? 0) > 0 ? (
        <section aria-label="Niedomknięte po terminie" className="rounded-xl border border-border bg-card px-4 py-3">
          <h2 className="text-sm font-semibold">
            Niedomknięte dłużej niż {query.data?.escalate_after_days} dni roboczych
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {query.data?.overdue.map((row) => (
              <li key={row.user_id}>
                <span className="font-medium">{row.name}</span> — {peoplePhrase(row.pairs)} · po:{" "}
                {row.departed.map(shortName).join(", ")} · od {shortDate(row.since)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export default function DepartedCarePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>}>
      <DepartedCareScreen />
    </Suspense>
  );
}
