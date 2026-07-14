"use client"

import { useQuery } from "@tanstack/react-query"
import { Target } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"

import type { Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

export function SourcesFunnelSection({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "sources", analyticsPeriod],
    queryFn: () => analyticsApi.sources(analyticsPeriod),
    staleTime: 5 * 60_000,
  })
  const sources = query.data?.data.sources ?? []

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-2">
        <Target className="h-5 w-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground">Źródła kandydatów</h2>
        <span className="ml-auto text-xs text-muted-foreground">first-touch · distinct candidates</span>
      </div>
      <StatsBoundary
        isLoading={query.isLoading}
        isFetching={query.isFetching && !query.isLoading}
        isError={query.isError}
        error={query.error}
        isEmpty={!query.data || sources.length === 0}
        quality={query.data?.quality}
        generatedAt={query.data?.generated_at}
        onRetry={() => query.refetch()}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Źródło</th>
                <th className="px-3 py-2 text-right font-medium">Kandydaci</th>
                <th className="px-3 py-2 text-right font-medium">Placementy</th>
                <th className="px-3 py-2 text-right font-medium">Hire rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sources.map((source) => (
                <tr key={source.source}>
                  <td className="px-3 py-2 font-medium text-foreground">{source.source}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{source.cohort_candidates}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{source.placed_by_period_end}</td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">
                    {source.hire_rate_pct.toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBoundary>
    </section>
  )
}
