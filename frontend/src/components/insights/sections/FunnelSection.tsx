"use client"

import { useQuery } from "@tanstack/react-query"
import { TrendingUp } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"

import type { Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

export function FunnelSection({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "recruitment", "funnel", analyticsPeriod, "insights"],
    queryFn: () => analyticsApi.recruitmentFunnel(analyticsPeriod),
    staleTime: 5 * 60_000,
  })
  const data = query.data?.data
  const stages = data
    ? [
        ["Weryfikacje", data.verified],
        ["Rekomendacje", data.recommended],
        ["Interview wewnętrzny", data.internal_interview],
        ["Interview klienta", data.client_interview],
        ["Placementy", data.placed],
      ] as const
    : []
  const max = Math.max(...stages.map(([, count]) => count), 1)

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <TrendingUp className="h-5 w-5 text-primary" />
        Lejek rekrutacyjny
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          pierwszy milestone kandydat × oferta
        </span>
      </h2>
      <StatsBoundary
        isLoading={query.isLoading}
        isFetching={query.isFetching && !query.isLoading}
        isError={query.isError}
        error={query.error}
        isEmpty={!query.data}
        quality={query.data?.quality}
        generatedAt={query.data?.generated_at}
        onRetry={() => query.refetch()}
      >
        <div className="space-y-3">
          {stages.map(([label, count]) => (
            <div key={label} className="flex items-center gap-3">
              <span className="w-40 truncate text-sm text-foreground">{label}</span>
              <div className="h-5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.max(2, (count / max) * 100)}%` }}
                />
              </div>
              <span className="w-12 text-right text-sm font-medium tabular-nums text-foreground">
                {count}
              </span>
            </div>
          ))}
        </div>
      </StatsBoundary>
    </section>
  )
}
