"use client"

import { useQuery } from "@tanstack/react-query"
import { Building2, CircleDollarSign, ReceiptText, TrendingUp } from "lucide-react"

import { StatsBoundary, type StatsQuality } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"

import type { Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

function pln(value: string | null): string {
  if (value == null) return "—"
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat("pl-PL", {
        style: "currency",
        currency: "PLN",
        maximumFractionDigits: 0,
      }).format(parsed)
    : `${value} PLN`
}

function combinedQuality(
  qualities: Array<StatsQuality | undefined>,
): StatsQuality | undefined {
  const present = qualities.filter((quality): quality is StatsQuality => Boolean(quality))
  if (present.length === 0) return undefined
  const status = present.some((quality) => quality.status === "unavailable")
    ? "unavailable"
    : present.some((quality) => quality.status === "partial")
      ? "partial"
      : "complete"
  return {
    status,
    warnings: [...new Set(present.flatMap((quality) => quality.warnings ?? []))],
  }
}

export function FinanceAnalyticsSection({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "finance", "bundle", analyticsPeriod],
    queryFn: async () => {
      const [summary, trend, clients] = await Promise.all([
        analyticsApi.financeSummary(analyticsPeriod),
        analyticsApi.financeTrend(analyticsPeriod),
        analyticsApi.financeClients(analyticsPeriod),
      ])
      return { summary, trend, clients }
    },
    staleTime: 5 * 60_000,
  })

  const summary = query.data?.summary.data
  const trend = query.data?.trend.data.months ?? []
  const clients = query.data?.clients.data.clients ?? []
  const quality = combinedQuality([
    query.data?.summary.quality,
    query.data?.trend.quality,
    query.data?.clients.quality,
  ])

  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <CircleDollarSign className="h-5 w-5 text-primary" />
        Finanse
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          PLN po kursie NBP
        </span>
      </h2>
      <StatsBoundary
        isLoading={query.isLoading}
        isFetching={query.isFetching && !query.isLoading}
        isError={query.isError}
        error={query.error}
        isEmpty={!query.data}
        quality={quality}
        generatedAt={query.data?.summary.generated_at}
        onRetry={() => query.refetch()}
      >
        {summary && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {(
                [
                  { label: "Przychód", value: pln(summary.totals.revenue), icon: CircleDollarSign },
                  { label: "Koszty", value: pln(summary.totals.costs), icon: ReceiptText },
                  { label: "Marża", value: pln(summary.totals.margin), icon: TrendingUp },
                  { label: "Aktywne kontrakty", value: String(summary.active_contracts), icon: Building2 },
                ] satisfies Array<{
                  label: string
                  value: string
                  icon: React.ComponentType<{ className?: string }>
                }>
              ).map(({ label, value, icon: Icon }) => (
                <div key={label} className="rounded-xl border border-border bg-card p-4">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Icon className="h-4 w-4 text-primary" />
                    {label}
                  </div>
                  <div className="mt-2 text-2xl font-bold text-foreground">{value}</div>
                </div>
              ))}
            </div>

            {trend.length > 0 && (
              <div className="rounded-xl border border-border bg-card p-4">
                <h3 className="mb-3 text-sm font-semibold text-foreground">Trend miesięczny</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-muted-foreground">
                      <tr>
                        <th className="py-2 text-left font-medium">Miesiąc</th>
                        <th className="py-2 text-right font-medium">Przychód</th>
                        <th className="py-2 text-right font-medium">Koszty</th>
                        <th className="py-2 text-right font-medium">Marża</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {trend.map((point) => (
                        <tr key={point.month}>
                          <td className="py-2 text-foreground">{point.month}</td>
                          <td className="py-2 text-right tabular-nums">{pln(point.totals.revenue)}</td>
                          <td className="py-2 text-right tabular-nums">{pln(point.totals.costs)}</td>
                          <td className="py-2 text-right tabular-nums">{pln(point.totals.margin)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">Klient</th>
                    <th className="px-4 py-3 text-right font-medium">Kontrakty</th>
                    <th className="px-4 py-3 text-right font-medium">Przychód</th>
                    <th className="px-4 py-3 text-right font-medium">Marża</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {clients.map((client) => (
                    <tr key={client.client_id}>
                      <td className="px-4 py-3 font-medium text-foreground">{client.client_name}</td>
                      <td className="px-4 py-3 text-right">{client.active_contracts}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{pln(client.totals.revenue)}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{pln(client.totals.margin)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {clients.length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  Brak danych finansowych klientów w wybranym okresie.
                </p>
              )}
            </div>
          </div>
        )}
      </StatsBoundary>
    </section>
  )
}
