"use client"

import { useQuery } from "@tanstack/react-query"
import { Users } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"

import { PERIOD_LABELS, type Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

/** Canonical team performance table; UserActivity is intentionally not used. */
export function ActivityHeatmap({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "team", "kpis", analyticsPeriod, "insights"],
    queryFn: () => analyticsApi.teamKpis(analyticsPeriod),
    staleTime: 60_000,
  })
  const rows = query.data?.data.users ?? []

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div className="mb-5 flex items-center gap-2">
        <Users className="h-5 w-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">KPI zespołu</h2>
        <span className="ml-auto text-xs text-muted-foreground">{PERIOD_LABELS[period]}</span>
      </div>
      <StatsBoundary
        isLoading={query.isLoading}
        isFetching={query.isFetching && !query.isLoading}
        isError={query.isError}
        error={query.error}
        isEmpty={!query.data || rows.length === 0}
        quality={query.data?.quality}
        generatedAt={query.data?.generated_at}
        staleAfterMs={2 * 60_000}
        onRetry={() => query.refetch()}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Osoba</th>
                <th className="px-3 py-2 text-right font-medium">Rozmowy</th>
                <th className="px-3 py-2 text-right font-medium">Weryfikacje</th>
                <th className="px-3 py-2 text-right font-medium">Kandydaci</th>
                <th className="px-3 py-2 text-right font-medium">Rekomendacje</th>
                <th className="px-3 py-2 text-right font-medium">Placementy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.user_id} className="hover:bg-muted/40">
                  <td className="px-3 py-2">
                    <div className="font-medium text-foreground">{row.user_name}</div>
                    <div className="text-xs text-muted-foreground">{row.primary_role}</div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.calls_available ? row.calls_completed ?? "—" : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.verifications}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.candidates_added}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.recommendations}</td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">{row.placements}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBoundary>
    </section>
  )
}
