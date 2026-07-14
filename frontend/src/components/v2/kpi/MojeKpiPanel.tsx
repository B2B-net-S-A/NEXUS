"use client"

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  CheckCircle2,
  FilePlus2,
  PhoneCall,
  Send,
  Target,
  Trophy,
} from "lucide-react"

import {
  analyticsApi,
  callsAreUnavailable,
  type PersonalKpiData,
} from "@/lib/analytics"
import { cn } from "@/lib/utils"
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth"
import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"

type Period = "day" | "week" | "month"

const PERIOD_LABEL: Record<Period, string> = {
  day: "Dziś",
  week: "Tydzień",
  month: "Miesiąc",
}

function KpiTile({
  title,
  value,
  subtitle,
  icon: Icon,
}: {
  title: string
  value: React.ReactNode
  subtitle: string
  icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </span>
      </div>
      <div className="text-3xl font-extrabold leading-none text-foreground">{value}</div>
      <div className="mt-1.5 text-xs text-muted-foreground">{subtitle}</div>
    </div>
  )
}

function metricTiles(data: PersonalKpiData, callsUnavailable: boolean) {
  return [
    {
      key: "calls",
      title: "Rozmowy",
      value: callsUnavailable ? "—" : data.calls_completed,
      subtitle: callsUnavailable
        ? "CloudTalk niedostępny"
        : `zakończone · cel ${data.targets.calls_daily}/dzień`,
      icon: PhoneCall,
    },
    {
      key: "verifications",
      title: "Weryfikacje",
      value: data.verifications,
      subtitle: `pierwsze osiągnięcie · cel ${data.targets.verifications_daily}/dzień`,
      icon: CheckCircle2,
    },
    {
      key: "candidates",
      title: "Kandydaci dodani",
      value: data.candidates_added,
      subtitle:
        data.targets.candidates_added_daily == null
          ? "utworzeni przez Ciebie"
          : `utworzeni · cel ${data.targets.candidates_added_daily}/dzień`,
      icon: FilePlus2,
    },
    {
      key: "recommendations",
      title: "Rekomendacje",
      value: data.recommendations,
      subtitle: "pierwsze CV wysłane do klienta",
      icon: Send,
    },
    {
      key: "placements",
      title: "Placementy",
      value: data.placements,
      subtitle: `pierwsze zatrudnienie · cel ${data.targets.placements_monthly}/mc`,
      icon: Trophy,
    },
    {
      key: "precision",
      title: "Precision · 30 dni",
      value:
        data.precision_30d.value_pct == null
          ? "—"
          : `${Math.round(data.precision_30d.value_pct)}%`,
      subtitle: `${data.precision_30d.recommended}/${data.precision_30d.verified} · cel ${data.targets.precision_pct}%`,
      icon: Target,
    },
  ]
}

/** Canonical personal KPI coach backed only by analytics v1 live ATS data. */
export function PersonalKpiCoach({ className }: { className?: string }) {
  const user = useAuthStore((state) => state.user)
  const canView = hasAnalyticsCapability(user, "view_personal_recruitment_kpis")
  const [period, setPeriod] = useState<Period>("day")
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["analytics-v1", "me", "kpis", period],
    queryFn: () => analyticsApi.personalKpis(period),
    enabled: canView,
    staleTime: 60_000,
  })

  if (!canView) return null

  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-4", className)}
      aria-label="Moje KPI"
    >
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">Moje KPI</h2>
          </div>
          {data && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Dane wygenerowane {new Date(data.generated_at).toLocaleString("pl-PL")}
            </p>
          )}
        </div>
        <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
          {(Object.keys(PERIOD_LABEL) as Period[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setPeriod(item)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                period === item
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PERIOD_LABEL[item]}
            </button>
          ))}
        </div>
      </header>

      <StatsBoundary
        isLoading={isLoading}
        isFetching={isFetching && !isLoading}
        isError={isError}
        error={error}
        isEmpty={!data}
        quality={data?.quality}
        generatedAt={data?.generated_at}
        staleAfterMs={2 * 60_000}
        onRetry={() => refetch()}
        loadingFallback={
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3" aria-label="Ładowanie KPI">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="h-24 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        }
      >
        {data && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            {metricTiles(
              data.data,
              !data.data.calls_available || callsAreUnavailable(data),
            ).map(({ key, ...tile }) => (
              <KpiTile key={key} {...tile} />
            ))}
          </div>
        )}
      </StatsBoundary>
    </section>
  )
}

/** Compatibility alias for existing dashboard imports. */
export const MojeKpiPanel = PersonalKpiCoach

export default PersonalKpiCoach
