"use client";

/**
 * Kto co przyniósł z linków, na osobę (makieta D,
 * https://claude.ai/artifact/BcevDUToiG7AGHfgY86T5P). Link ogólny osobno od linków
 * do rekrutacji. Dane imienne: admin, Head of Recruitment i Delivery Lead.
 */

import { useQuery } from "@tanstack/react-query";
import { Link2, Loader2 } from "lucide-react";

import { formatDate } from "@/components/v2/career-share/share-utils";
import {
  type InsightsPeriodParams,
  insightsApi,
  insightsQueryKeys,
} from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count } from "./InsightsFormat";
import { SectionError } from "./_shared";

const NUMBER_COLUMNS = [
  { key: "visits", label: "Wejścia w okresie" },
  { key: "visits_total", label: "Wejścia od początku" },
  { key: "applications_general", label: "Zgł. ogólny" },
  { key: "applications_job", label: "Zgł. rekrutacje" },
  { key: "new_candidates", label: "Nowi w bazie" },
  { key: "in_process", label: "W rekrutacji" },
  { key: "cv_sent", label: "CV wysłane" },
  { key: "hired", label: "Zatrudnieni" },
] as const;

export function InsightsLinkPeople({ period }: { period: InsightsPeriodParams }) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.linkPeople(period),
    queryFn: () => insightsApi.linkPeople(period),
  });
  const rows = data?.rows ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  if (viewState === "loading") {
    return (
      <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </section>
    );
  }
  if (isBlockingViewState(viewState)) {
    return <SectionError label="Linki aplikacyjne" error={error} onRetry={() => void refetch()} />;
  }

  const totals = data?.totals;
  const tiles: [string, number | undefined][] = [
    ["Aktywne linki", totals?.links],
    ["Linki bez żadnego wejścia", totals?.links_without_visits],
    ["Wejścia w okresie", totals?.visits],
    ["Zgłoszenia w okresie", totals?.applications],
  ];

  return (
    <section className="space-y-4" data-testid="insights-link-people">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Link2 className="h-5 w-5 text-primary" />
        Kto co przyniósł
      </h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border bg-card px-4 py-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-xl font-semibold tabular-nums text-foreground">{count(value)}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        {data?.visits_tracked_from
          ? `Wejścia dzień po dniu zapisujemy od ${formatDate(data.visits_tracked_from)}, starsze są tylko w kolumnie „Wejścia od początku”.`
          : "Wejścia dzień po dniu jeszcze się nie zebrały. Suma jest w kolumnie „Wejścia od początku”."}
      </p>
      {viewState === "empty" ? (
        <div className="rounded-xl border border-border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
          Nikt nie ma jeszcze linku aplikacyjnego.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Osoba</th>
                <th className="px-3 py-2 text-center font-medium">Link ogólny</th>
                <th className="px-3 py-2 text-right font-medium">Linki do rekrutacji</th>
                {NUMBER_COLUMNS.map((column) => (
                  <th key={column.key} className="px-3 py-2 text-right font-medium">
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.user_id} className="border-t border-border">
                  <td className="px-3 py-1.5 font-medium text-foreground">{row.name}</td>
                  <td className="px-3 py-1.5 text-center text-muted-foreground">
                    {row.general_link ? "tak" : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{row.job_links}</td>
                  {NUMBER_COLUMNS.map((column) => (
                    <td key={column.key} className="px-3 py-1.5 text-right tabular-nums">
                      {row[column.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
