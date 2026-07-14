"use client"

import { useQuery } from "@tanstack/react-query"
import { Briefcase, CircleDollarSign, Target, Trophy, Users } from "lucide-react"

import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
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

function Metric({
  label,
  value,
  icon: Icon,
  detail,
}: {
  label: string
  value: React.ReactNode
  icon: React.ComponentType<{ className?: string }>
  detail?: string
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Icon className="h-4 w-4 text-primary" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold text-foreground">{value}</div>
      {detail && <div className="mt-1 text-xs text-muted-foreground">{detail}</div>}
    </div>
  )
}

export function BoardKPI({ period }: { period: Period }) {
  const analyticsPeriod = PERIOD_MAP[period]
  const query = useQuery({
    queryKey: ["analytics-v1", "executive", "board", analyticsPeriod],
    queryFn: () => analyticsApi.executiveBoard(analyticsPeriod),
    staleTime: 5 * 60_000,
  })

  const board = query.data?.data

  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Trophy className="h-5 w-5 text-primary" />
        Board KPI
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          PLN · Europe/Warsaw
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
        {board && (
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <Metric
              label="Placementy"
              value={board.overview.pipeline.placements}
              icon={Users}
            />
            <Metric
              label="Aktywne kontrakty"
              value={board.overview.contracts.active}
              detail={`${board.overview.contracts.expiring_30_days} wygasa w 30 dni`}
              icon={Briefcase}
            />
            <Metric
              label="Przychód"
              value={pln(board.finance.totals.revenue)}
              detail="po konwersji NBP"
              icon={CircleDollarSign}
            />
            <Metric
              label="Marża"
              value={pln(board.finance.totals.margin)}
              detail={
                board.finance.totals.margin_pct == null
                  ? "brak wiarygodnego mianownika"
                  : `${board.finance.totals.margin_pct.toFixed(1)}% przychodu`
              }
              icon={Target}
            />
            <Metric
              label="Przetargi"
              value={board.tenders.total}
              detail={`${board.tenders.unknown} bez wyniku`}
              icon={Trophy}
            />
            <Metric
              label="Win rate"
              value={
                board.tenders.win_rate_pct == null
                  ? "—"
                  : `${board.tenders.win_rate_pct.toFixed(1)}%`
              }
              detail={`${board.tenders.won} wygranych · ${board.tenders.lost} przegranych`}
              icon={Target}
            />
          </div>
        )}
      </StatsBoundary>
    </section>
  )
}
