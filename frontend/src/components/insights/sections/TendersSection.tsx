"use client"

import { useQuery } from "@tanstack/react-query"
import { FileQuestion, FileText, Target, Trophy, XCircle } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import { analyticsApi } from "@/lib/analytics"
import { cn } from "@/lib/utils"

import type { Period } from "./PeriodSelector"

const PERIOD_MAP: Record<Period, "day" | "week" | "month" | "quarter"> = {
  today: "day",
  week: "week",
  month: "month",
  quarter: "quarter",
}

const OUTCOME_LABEL: Record<string, string> = {
  won: "Wygrany",
  lost: "Przegrany",
  pending: "W toku",
  unknown: "Brak wyniku",
}

function outcomeTone(outcome: string): string {
  if (outcome === "won") return "bg-success-muted text-success-muted-foreground"
  if (outcome === "lost") return "bg-destructive-muted text-destructive-muted-foreground"
  if (outcome === "pending") return "bg-info-muted text-info-muted-foreground"
  return "bg-warning-muted text-warning-muted-foreground"
}

function CountCard({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: React.ReactNode
  icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        {label}
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <div className="mt-2 text-2xl font-bold text-foreground">{value}</div>
    </div>
  )
}

export function TendersSection({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "commercial", "tenders", analyticsPeriod],
    queryFn: () => analyticsApi.commercialTenders(analyticsPeriod),
    staleTime: 5 * 60_000,
  })
  const data = query.data?.data

  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Trophy className="h-5 w-5 text-primary" />
        Przetargi
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
        {data && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <CountCard label="Wszystkie" value={data.total} icon={FileText} />
              <CountCard label="Wygrane" value={data.won} icon={Trophy} />
              <CountCard label="Przegrane" value={data.lost} icon={XCircle} />
              <CountCard label="Brak wyniku" value={data.unknown} icon={FileQuestion} />
              <CountCard
                label="Win rate"
                value={data.win_rate_pct == null ? "—" : `${data.win_rate_pct.toFixed(1)}%`}
                icon={Target}
              />
            </div>

            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">Przetarg</th>
                    <th className="px-4 py-3 text-left font-medium">Klient</th>
                    <th className="px-4 py-3 text-left font-medium">Wynik</th>
                    <th className="px-4 py-3 text-right font-medium">Data zdarzenia</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {data.tenders.map((tender) => (
                    <tr key={tender.job_id}>
                      <td className="px-4 py-3 font-medium text-foreground">{tender.job_title}</td>
                      <td className="px-4 py-3 text-muted-foreground">{tender.client_name}</td>
                      <td className="px-4 py-3">
                        <span className={cn("rounded-full px-2 py-1 text-xs font-medium", outcomeTone(tender.outcome))}>
                          {OUTCOME_LABEL[tender.outcome] ?? tender.outcome}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-muted-foreground">
                        {new Date(tender.event_at).toLocaleDateString("pl-PL")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.tenders.length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  Brak przetargów w wybranym okresie.
                </p>
              )}
            </div>
          </div>
        )}
      </StatsBoundary>
    </section>
  )
}
