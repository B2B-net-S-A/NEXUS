"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  PROPOSAL_EXPIRED_HINT,
  PROPOSAL_OUTCOME_REASON_LABEL,
  PROPOSAL_OUTCOME_REASONS,
  PROPOSAL_OUTCOME_SOURCE_LABEL,
  PROPOSAL_OUTCOME_WINDOWS,
  decisionRate,
  insightsProposalsApi,
  insightsProposalsQueryKeys,
  type ProposalOutcomeCounts,
} from "@/lib/insights-proposals-api";
import { SectionError } from "@/components/insights/sections/_shared";
import { cn } from "@/lib/utils";
import { PanelLoading } from "./ViewKit";

/**
 * Raport „Propozycje AI": co zespół robi z propozycjami z bazy — dodaje,
 * pomija (z powodem) czy zostawia bez decyzji. Awaria = błąd z „Ponów",
 * nigdy pusta lista.
 */
export function ProposalOutcomesReport() {
  const [days, setDays] = useState<number>(7);
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsProposalsQueryKeys.outcomes(days),
    queryFn: () => insightsProposalsApi.outcomes(days),
  });

  return (
    <div className="space-y-4">
      <div role="group" aria-label="Okno czasu" className="flex flex-wrap gap-1.5">
        {PROPOSAL_OUTCOME_WINDOWS.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={days === value}
            onClick={() => setDays(value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium",
              days === value
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            {value} dni
          </button>
        ))}
      </div>
      {isPending ? (
        <PanelLoading />
      ) : isError || !data ? (
        <SectionError label="Propozycje AI" error={error} onRetry={() => void refetch()} />
      ) : data.totals.proposed === 0 ? (
        <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
          W ostatnich {data.days} dniach nie było nowych propozycji
          {data.scope === "delivery_lead" ? " w Twoich rekrutacjach" : ""}.
        </p>
      ) : (
        <>
          <Summary counts={data.totals} days={data.days} />
          <ReasonBreakdown counts={data.totals} />
          <SourceTable rows={data.by_source} />
          <JobTable rows={data.jobs} />
        </>
      )}
    </div>
  );
}

function Summary({ counts, days }: { counts: ProposalOutcomeCounts; days: number }) {
  const rate = decisionRate(counts);
  const expired = counts.expired ?? 0;
  const tiles: Array<{ label: string; value: number; hint?: string }> = [
    { label: "Zaproponowano osób", value: counts.proposed },
    { label: "Dodano do rekrutacji", value: counts.added },
    { label: "Pominięto", value: counts.dismissed },
    { label: "Czeka na decyzję", value: counts.pending },
  ];
  // Kafel tylko, gdy coś wygasło — zero w piątym kaflu byłoby szumem.
  if (expired > 0) tiles.push({ label: "Wygasło", value: expired, hint: PROPOSAL_EXPIRED_HINT });
  return (
    <section aria-label="Podsumowanie" className="space-y-2">
      <div className={cn("grid grid-cols-2 gap-3", tiles.length > 4 ? "md:grid-cols-5" : "md:grid-cols-4")}>
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-xl border border-border bg-card p-4" title={tile.hint}>
            <p className="text-xs text-muted-foreground">{tile.label}</p>
            <p className="text-2xl font-semibold tabular-nums text-foreground">{tile.value}</p>
          </div>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {rate === null
          ? "Brak propozycji w tym oknie."
          : `Decyzję (dodanie albo pominięcie) ma ${rate}% propozycji z ostatnich ${days} dni.`}
      </p>
    </section>
  );
}

function ReasonBreakdown({ counts }: { counts: ProposalOutcomeCounts }) {
  if (counts.dismissed === 0) return null;
  return (
    <section aria-label="Powody pominięcia" className="rounded-xl border border-border bg-card p-4">
      <h3 className="mb-2 text-sm font-semibold text-foreground">Dlaczego pomijamy</h3>
      <ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        {PROPOSAL_OUTCOME_REASONS.filter((r) => (counts.dismissed_by_reason[r] ?? 0) > 0).map((reason) => (
          <li key={reason} className="flex justify-between gap-3">
            <span>{PROPOSAL_OUTCOME_REASON_LABEL[reason]}</span>
            <span className="font-semibold tabular-nums">{counts.dismissed_by_reason[reason]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const COUNT_COLUMNS: Array<{
  key: keyof Omit<ProposalOutcomeCounts, "dismissed_by_reason">;
  label: string;
  hint?: string;
}> = [
  { key: "proposed", label: "Zaproponowano" },
  { key: "added", label: "Dodano" },
  { key: "dismissed", label: "Pominięto" },
  { key: "pending", label: "Czeka" },
  { key: "expired", label: "Wygasłe", hint: PROPOSAL_EXPIRED_HINT },
];

function CountHeader({ column }: { column: (typeof COUNT_COLUMNS)[number] }) {
  return (
    <th
      className={cn("px-3 py-2.5 text-right font-semibold", column.hint && "cursor-help")}
      title={column.hint}
    >
      {column.label}
    </th>
  );
}

function SourceTable({ rows }: { rows: Array<ProposalOutcomeCounts & { source: string }> }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-semibold text-foreground">Według źródła</h3>
      <p className="text-xs text-muted-foreground">
        Osoba zaproponowana przez dwa źródła liczy się w obu — suma bywa większa niż podsumowanie.
      </p>
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 bg-card px-4 py-2.5 text-left font-semibold">Źródło</th>
              {COUNT_COLUMNS.map((c) => (
                <CountHeader key={c.key} column={c} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.source} className="border-b border-border/60 last:border-b-0">
                <td className="sticky left-0 bg-card px-4 py-2.5">
                  {PROPOSAL_OUTCOME_SOURCE_LABEL[row.source] ?? row.source}
                </td>
                {COUNT_COLUMNS.map((c) => (
                  <td key={c.key} className="px-3 py-2.5 text-right tabular-nums">{row[c.key] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function JobTable({ rows }: { rows: Array<ProposalOutcomeCounts & { job_id: number; title: string | null }> }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-semibold text-foreground">Według rekrutacji</h3>
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 bg-card px-4 py-2.5 text-left font-semibold">Rekrutacja</th>
              {COUNT_COLUMNS.map((c) => (
                <CountHeader key={c.key} column={c} />
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.job_id} className="border-b border-border/60 last:border-b-0">
                <td className="sticky left-0 bg-card px-4 py-2.5">
                  <Link
                    href={`/jobs/${row.job_id}?tab=similar`}
                    className="font-medium text-primary hover:underline"
                  >
                    {row.title ?? `Rekrutacja #${row.job_id}`}
                  </Link>
                </td>
                {COUNT_COLUMNS.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      "px-3 py-2.5 text-right tabular-nums",
                      c.key === "pending" && row.pending > 0 && "font-semibold text-foreground",
                    )}
                  >
                    {row[c.key] ?? 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
