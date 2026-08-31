"use client"

import { CheckCircle2, Target } from "lucide-react"

import { StatCard } from "@/components/ds"
import { KpiProgressBar } from "@/components/v2/kpi/KpiProgressBar"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useMyKpis } from "@/hooks/useMyKpis"
import type { KpiResult } from "@/lib/api"
import { cn } from "@/lib/utils"

const DAILY_TARGET_ID = "daily_first_verifications"

const STATE_COPY: Record<KpiResult["state"], string> = {
  hit: "Cel osiągnięty",
  ahead: "Jesteś powyżej planu",
  on_track: "Jesteś na dobrej drodze",
  behind: "Potrzebne przyspieszenie",
  missed: "Cel nie został osiągnięty",
}

function formatHours(hours: number): string {
  if (hours <= 0) return "Dzień pracy zakończony"
  if (hours < 1) return "Mniej niż godzina do końca dnia pracy"
  const rounded = Math.ceil(hours)
  return `${rounded} h do końca dnia pracy`
}

interface DailyRecruiterKpiProps {
  variant?: "full" | "compact"
  fallbackOpenProcesses?: number
}

export function DailyRecruiterKpi({
  variant = "full",
  fallbackOpenProcesses,
}: DailyRecruiterKpiProps = {}) {
  const query = useMyKpis()

  if (query.isLoading) {
    return (
      <Skeleton
        className={cn(
          "w-full rounded-xl",
          variant === "compact" ? "h-32" : "h-48",
        )}
      />
    )
  }

  if (query.isError) {
    if (variant === "compact") {
      return (
        <StatCard
          label="Twój cel na dziś"
          value="—"
          icon={Target}
          sub="Cel jest chwilowo niedostępny"
        />
      )
    }

    return (
      <Card className="border-destructive/30">
        <CardContent className="flex items-center justify-between gap-4 p-5">
          <div>
            <p className="text-sm font-medium text-foreground">
              Nie udało się pobrać Twojego celu na dziś.
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Pozostałe dane dashboardu nadal są dostępne.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 text-sm font-medium text-primary hover:underline"
            onClick={() => void query.refetch()}
          >
            Ponów
          </button>
        </CardContent>
      </Card>
    )
  }

  const kpi = query.data?.find((item) => item.kpi_id === DAILY_TARGET_ID)
  if (!kpi) {
    if (variant === "compact" && fallbackOpenProcesses !== undefined) {
      return (
        <StatCard
          label="Otwarte rekrutacje"
          value={fallbackOpenProcesses}
          icon={Target}
          sub="W Twoim zakresie"
        />
      )
    }
    return null
  }

  const remaining = Math.max(kpi.target - kpi.current, 0)
  const completed = remaining === 0

  if (variant === "compact") {
    return (
      <Card
        className={cn(
          "p-5 transition-shadow duration-200 hover:shadow-xs",
          completed && "border-success/30 bg-success-muted/40",
        )}
        data-testid="daily-recruiter-kpi"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-md",
                completed
                  ? "bg-success-muted text-success-muted-foreground"
                  : "bg-primary/10 text-primary",
              )}
            >
              {completed ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <Target className="h-3.5 w-3.5" />
              )}
            </span>
            <span className="text-[13px] font-medium text-muted-foreground">
              Twój cel na dziś
            </span>
          </div>
          <span className="text-xs font-medium tabular-nums text-muted-foreground">
            {Math.round(kpi.progress_pct)}%
          </span>
        </div>

        <div className="mt-4 flex items-baseline gap-2">
          <span className="text-[32px] font-semibold leading-none tracking-tight tabular-nums text-foreground">
            {kpi.current} / {kpi.target}
          </span>
          <span className="text-xs text-muted-foreground">weryfikacji</span>
        </div>
        <KpiProgressBar
          id={kpi.kpi_id}
          progressPct={kpi.progress_pct}
          state={kpi.state}
          label={`${Math.round(kpi.progress_pct)}%`}
          variant="full"
          className="mt-4"
        />
        <p className="mt-2.5 text-xs text-muted-foreground">
          {completed ? STATE_COPY[kpi.state] : `Pozostało: ${remaining}`} ·{" "}
          {formatHours(kpi.deadline_hours_left)}
        </p>
      </Card>
    )
  }

  return (
    <Card
      className={cn(
        "overflow-hidden border-primary/20",
        completed && "border-success/30 bg-success-muted/40",
      )}
      data-testid="daily-recruiter-kpi"
    >
      <CardContent className="p-5 md:p-6">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              {completed ? (
                <CheckCircle2 className="h-4 w-4 text-success" />
              ) : (
                <Target className="h-4 w-4 text-primary" />
              )}
              Twój cel na dziś
            </div>

            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-4xl font-semibold tabular-nums text-foreground md:text-5xl">
                {kpi.current}
              </span>
              <span className="text-lg text-muted-foreground">
                z {kpi.target} weryfikacji
              </span>
            </div>

            <KpiProgressBar
              id={kpi.kpi_id}
              progressPct={kpi.progress_pct}
              state={kpi.state}
              label={`${Math.round(kpi.progress_pct)}%`}
              variant="full"
              className="mt-5"
            />
          </div>

          <div className="rounded-lg bg-muted/60 px-4 py-3 md:min-w-52">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {completed ? "Status" : "Zostało"}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
              {completed ? "Gotowe" : remaining}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {STATE_COPY[kpi.state]} · {formatHours(kpi.deadline_hours_left)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
