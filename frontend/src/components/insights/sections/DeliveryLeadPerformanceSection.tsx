"use client"

import { useQuery } from "@tanstack/react-query"
import { Users } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"

import type { Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

export function DeliveryLeadPerformanceSection({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "delivery-leads", analyticsPeriod],
    queryFn: () => analyticsApi.deliveryLeadPerformance(analyticsPeriod),
    staleTime: 5 * 60_000,
  })
  const rows = query.data?.data.delivery_leads ?? []

  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Users className="h-5 w-5 text-primary" />
        Wyniki Delivery Leadów
      </h2>
      <StatsBoundary
        isLoading={query.isLoading}
        isFetching={query.isFetching && !query.isLoading}
        isError={query.isError}
        error={query.error}
        isEmpty={!query.data || rows.length === 0}
        quality={query.data?.quality}
        generatedAt={query.data?.generated_at}
        onRetry={() => query.refetch()}
      >
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Delivery Lead</th>
                <th className="px-4 py-3 text-right font-medium">Oferty</th>
                <th className="px-4 py-3 text-right font-medium">Weryfikacje</th>
                <th className="px-4 py-3 text-right font-medium">Rekomendacje</th>
                <th className="px-4 py-3 text-right font-medium">Placementy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.user_id}>
                  <td className="px-4 py-3 font-medium text-foreground">{row.user_name}</td>
                  <td className="px-4 py-3 text-right">{row.jobs}</td>
                  <td className="px-4 py-3 text-right">{row.verifications}</td>
                  <td className="px-4 py-3 text-right">{row.recommendations}</td>
                  <td className="px-4 py-3 text-right font-semibold">{row.placements}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatsBoundary>
    </section>
  )
}
