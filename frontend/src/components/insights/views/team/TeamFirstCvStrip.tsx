"use client"

// Pas „Od otwarcia rekrutacji do pierwszego CV u klienta” (audyt 2, makieta C1).
// Stałe okno 8 tygodni, niezależne od okresu zakładki: czas do CV to cecha
// otwartych rekrutacji, a nie miesiąca kalendarzowego.

import { useQuery } from "@tanstack/react-query"

import { Sparkline } from "@/components/ds/StatCard"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { Skeleton } from "@/components/ui/skeleton"
import {
  FIRST_CV_QUERY_KEY,
  fetchFirstCv,
  pctLabel,
  shortDate,
  workdaysLabel,
  type FirstCvSummary,
} from "@/lib/client-response"
import { cn } from "@/lib/utils"

interface StripTileProps {
  label: string
  value: string
  caption: string
  trend?: number[]
  emphasis?: boolean
}

function StripTile({ label, value, caption, trend, emphasis }: StripTileProps) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <p
          className={cn(
            "text-2xl font-semibold tabular-nums",
            emphasis ? "text-primary" : "text-foreground",
          )}
        >
          {value}
        </p>
        {trend && trend.length >= 2 ? (
          <Sparkline points={trend} className="text-primary" />
        ) : null}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{caption}</p>
    </div>
  )
}

function trendOf(
  data: FirstCvSummary,
  pick: (week: FirstCvSummary["weeks"][number]) => number | null,
): number[] {
  return data.weeks.map(pick).filter((v): v is number => v !== null)
}

export function TeamFirstCvStrip() {
  const query = useQuery({
    queryKey: FIRST_CV_QUERY_KEY,
    queryFn: fetchFirstCv,
    staleTime: 5 * 60_000,
  })

  if (query.isPending) return <Skeleton className="h-28 w-full rounded-xl" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const data = query.data
  return (
    <section aria-label="Od otwarcia rekrutacji do pierwszego CV u klienta">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold text-foreground">
          Od otwarcia rekrutacji do pierwszego CV u klienta
        </h3>
        <p className="text-xs text-muted-foreground">
          rekrutacje otwarte od {shortDate(data.window_from)}, dni robocze, bez importu
          z Traffita
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StripTile
          label="Pierwsza ruszona karta"
          value={workdaysLabel(data.median_first_moved_workdays)}
          caption="mediana"
        />
        <StripTile
          label="Pierwszy „Zweryfikowany”"
          value={workdaysLabel(data.median_first_verified_workdays)}
          caption="mediana"
        />
        <StripTile
          label="Pierwsze CV u klienta"
          value={workdaysLabel(data.median_first_cv_workdays)}
          caption={`mediana · ${data.jobs_with_cv} z ${data.opened_jobs} z CV`}
          trend={trendOf(data, (week) => week.median_first_cv_workdays)}
          emphasis
        />
        <StripTile
          label={`CV w ${data.sla_workdays} dni rob.`}
          value={pctLabel(data.sla_pct)}
          caption={`${data.sla_within_jobs} z ${data.sla_eligible_jobs} rekrutacji`}
          trend={trendOf(data, (week) => week.sla_pct)}
          emphasis
        />
      </div>
    </section>
  )
}
