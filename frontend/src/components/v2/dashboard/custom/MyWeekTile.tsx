"use client"

// Kafelek „Twój tydzień": weryfikacje tygodnia wobec celu, CV wysłane do
// klienta w tym tygodniu i placementy miesiąca wobec celu. Liczby z
// `/api/kpis/me/panel` — ta sama atrybucja i ten sam klucz zapytania co
// Insights → „Mój miesiąc”, więc obie powierzchnie pokazują to samo.
// Cel tygodnia liczy backend z dni pracy osoby (`person_workdays`: święta,
// urlop, dzień onboardingu) — kafelek go nie przelicza (14.11.2026).

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { api, type MyKpiPanel } from "@/lib/api"

export const MY_WEEK_QUERY_KEY = ["insights", "me", "panel"] as const

/** Cel, który da się pokazać: dodatnia liczba; reszta = brak celu. */
function usableTarget(value: number | null | undefined): number | null {
  return typeof value === "number" && value > 0 ? value : null
}

function WeekRow({
  label,
  value,
  target,
}: {
  label: string
  value: number
  target: number | null
}) {
  const percent = target ? Math.min(100, Math.round((value / target) * 100)) : null
  return (
    <div className="flex flex-col gap-1" data-testid="my-week-row">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-foreground">{label}</span>
        <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
          {value}
          {target !== null ? (
            <span className="font-normal text-muted-foreground"> / {target}</span>
          ) : null}
        </span>
      </div>
      {percent !== null ? (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
          <div
            className={percent >= 100 ? "h-full rounded-full bg-success" : "h-full rounded-full bg-primary"}
            style={{ width: `${percent}%` }}
          />
        </div>
      ) : null}
    </div>
  )
}

export function MyWeekTile() {
  const query = useQuery({
    queryKey: MY_WEEK_QUERY_KEY,
    queryFn: () => api.get<MyKpiPanel>("/api/kpis/me/panel").then((r) => r.data),
    staleTime: 60_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const panel = query.data
  if (panel.applies === false) {
    return <p className="text-sm text-muted-foreground">Ta rola nie ma celów KPI.</p>
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <WeekRow
        label="Weryfikacje w tym tygodniu"
        value={panel.weryfikacje.week}
        target={usableTarget(panel.target_verifications_week_to_date)}
      />
      <WeekRow label="CV do klienta w tym tygodniu" value={panel.rekomendacje.week} target={null} />
      <WeekRow
        label="Placementy w miesiącu"
        value={panel.placementy_month}
        target={usableTarget(panel.target_placements_monthly)}
      />
      <Link
        href="/insights?tab=moj-miesiac"
        className="mt-auto self-start text-sm font-medium text-primary hover:underline"
      >
        Mój miesiąc →
      </Link>
    </div>
  )
}
