"use client"

import { useState } from "react"
import dynamic from "next/dynamic"
import { useQuery } from "@tanstack/react-query"
import {
  BadgeCheck,
  CalendarClock,
  Send,
  Trophy,
  UserCheck,
  Users,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { StatCard, StatCardGrid } from "@/components/ds"
import { useCapability } from "@/hooks/useCapability"
import { cn } from "@/lib/utils"
import {
  getRecruitmentStats,
  type DashboardKpi,
  type RecruitmentStatsKpis,
} from "@/lib/dashboard-v2-api"
import type { DashboardPeriod } from "@/lib/dashboard-presets"
import { useAuthStore } from "@/store/auth"

import { RecruitmentCompetitions } from "./RecruitmentCompetitions"
import { RecruitmentLinkedInPanel } from "./RecruitmentLinkedInPanel"
import { RecruitmentTeamTable } from "./RecruitmentTeamTable"
import { StatsBoundary, type StatsBoundaryState } from "./StatsBoundary"

// Recharts (~100 kB) statycznie w tym module oznaczał, że KAŻDE otwarcie
// /dashboard płaci za wykres trendu, także gdy użytkownik nigdy do niego nie
// doscrolluje albo gdy sekcja renderuje pusty/niedostępny stan. `ssr: false`,
// bo wykres i tak liczy wymiary z DOM. Placeholder trzyma wysokość, żeby
// doładowanie nie przeskakiwało treścią pod kursorem.
const RecruitmentTrendChart = dynamic(
  () => import("./RecruitmentTrendChart").then((m) => m.RecruitmentTrendChart),
  {
    ssr: false,
    loading: () => (
      <div className="h-[320px] rounded-lg border border-border bg-card" />
    ),
  }
)

// Sekcja „Statystyki rekrutacji" — wspólna dla WSZYSTKICH presetów
// /dashboard (decyzja właściciela 2026-08-07: każda rola operacyjna widzi
// wyniki całego zespołu, jak w InfraReporterze). Legacy viewer `user` nie
// montuje sekcji; `finance` ma tier operacyjny od 19.08 i backendowy
// OperationalUser odpowiada mu 200 — bramka węższa od API chowałaby dane,
// do których użytkownik ma prawo. Okres sekcji jest NIEZALEŻNY od okresu
// presetu — własny selektor, default MIESIĄC.

const PERIODS: { value: DashboardPeriod; label: string }[] = [
  { value: "day", label: "Dziś" },
  { value: "week", label: "Tydzień" },
  { value: "month", label: "Miesiąc" },
  { value: "quarter", label: "Kwartał" },
  { value: "year", label: "Rok" },
]

const TILES: {
  metric: keyof RecruitmentStatsKpis
  label: string
  icon: LucideIcon
}[] = [
  { metric: "verifications", label: "Weryfikacje", icon: UserCheck },
  { metric: "recommendations", label: "Rekomendacje", icon: Send },
  { metric: "interviews", label: "Interviews", icon: CalendarClock },
  { metric: "acceptances", label: "Akceptacje", icon: BadgeCheck },
  { metric: "placements", label: "Placements", icon: Trophy },
]

function formatKpiValue(kpi: DashboardKpi | undefined): string {
  if (!kpi || kpi.value === null || kpi.quality === "unavailable") return "—"
  return String(kpi.value)
}

// Ten sam kontrakt co boundaryState w DashboardV2Preset (koperta v2 zna
// też "stale", którego analytics-owy deriveBoundaryState nie obsługuje).
function boundaryState(
  query: {
    isLoading: boolean
    isFetching: boolean
    isError: boolean
    error: unknown
  },
  quality?: { status: string },
): StatsBoundaryState {
  if (query.isLoading) return "loading"
  if (query.isError) {
    const status = (query.error as { response?: { status?: number } })?.response
      ?.status
    return status === 403 ? "forbidden" : "error"
  }
  if (quality?.status === "unavailable") return "unavailable"
  if (quality?.status === "partial") return "partial"
  if (quality?.status === "stale") return "stale"
  if (query.isFetching) return "refreshing"
  return "ready"
}

export function RecruitmentStatsSection({ className }: { className?: string }) {
  const user = useAuthStore((s) => s.user)
  // GET /api/dashboard/v2/recruitment-stats → OperationalUser. Ręczna lista
  // gubiła tu `finance`; rejestr trzyma zbiór razem z nazwą guardu backendu.
  const canView = useCapability("dashboard.recruitment_stats.view")

  // Domyślnie miesiąc (decyzja właściciela) — niezależnie od `?period=` strony.
  const [period, setPeriod] = useState<DashboardPeriod>("month")

  // Cache nie może przeciekać między rolami/impersonacją — klucz zawiera
  // tożsamość, wersję autoryzacji, scope i capabilities (wzorzec
  // DashboardV2Preset).
  const scopeCacheKey = user?.data_scope
    ? JSON.stringify({
        kind: user.data_scope.kind,
        userId: user.data_scope.user_id,
        clientIds: [...user.data_scope.allowed_client_ids].sort((a, b) => a - b),
        tacUserIds: [...user.data_scope.allowed_tac_user_ids].sort(
          (a, b) => a - b,
        ),
        operatorUserIds: [...user.data_scope.allowed_operator_user_ids].sort(
          (a, b) => a - b,
        ),
        clientTacPairs: [
          ...(user.data_scope.allowed_client_tac_pairs ?? []),
        ].sort(
          (a, b) => a.client_id - b.client_id || a.tac_user_id - b.tac_user_id,
        ),
      })
    : null
  const capabilityCacheKey = Array.from(
    new Set([
      ...(user?.capabilities ?? []),
      ...(user?.analytics_capabilities ?? []),
    ]),
  )
    .sort()
    .join(",")

  const query = useQuery({
    queryKey: [
      "recruitment-stats",
      period,
      user?.id ?? null,
      user?.authorization_version ?? null,
      scopeCacheKey,
      capabilityCacheKey,
    ],
    queryFn: () => getRecruitmentStats(period),
    enabled: Boolean(user) && canView,
    staleTime: 60_000,
  })

  if (!canView) return null

  const state = boundaryState(query, query.data?.data_quality)

  const data = query.data?.data
  const sections = query.data?.data_quality.sections

  return (
    <section
      className={cn("space-y-4", className)}
      aria-label="Statystyki rekrutacji"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">
            Statystyki rekrutacji
          </h2>
          {data ? (
            <span className="text-xs text-muted-foreground">
              ·{" "}
              {new Date(data.period.start).toLocaleDateString("pl-PL")} –{" "}
              {new Date(data.period.end).toLocaleDateString("pl-PL")}
            </span>
          ) : null}
        </div>
        <div
          className="inline-flex rounded-lg border border-border p-0.5 text-xs"
          role="group"
          aria-label="Okres statystyk rekrutacji"
        >
          {PERIODS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setPeriod(p.value)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                period === p.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
      </header>

      <StatsBoundary
        state={state}
        warnings={query.data?.data_quality.warnings}
        onRetry={() => query.refetch()}
      >
        {data ? (
          <div className="space-y-4">
            {/* 5 kafli — zawsze równe stopce „Razem" tabeli (te same totals) */}
            <StatCardGrid className="sm:grid-cols-3 lg:grid-cols-5">
              {TILES.map(({ metric, label, icon }) => {
                const kpi = data.kpis[metric]
                return (
                  <StatCard
                    key={metric}
                    label={label}
                    value={formatKpiValue(kpi)}
                    icon={icon}
                    sub={
                      kpi?.quality === "unavailable"
                        ? "Dane niedostępne — to nie jest zero"
                        : kpi?.definition
                    }
                  />
                )
              })}
            </StatCardGrid>

            {/* Tabela per osoba — pełna imienna dla każdej roli operacyjnej */}
            <div className="rounded-xl border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-semibold text-foreground">
                KPI zespołu — per osoba
              </h3>
              {data.team_table ? (
                <RecruitmentTeamTable table={data.team_table} />
              ) : (
                <p className="py-6 text-center text-xs text-muted-foreground">
                  {sections?.team_funnel?.status === "unavailable"
                    ? "Dane zespołu są chwilowo niedostępne (to NIE jest zero)."
                    : "Brak danych zespołu w wybranym okresie."}
                </p>
              )}
            </div>

            {/* Trend 12-mies. + lejek konwersji za wybrany okres */}
            <RecruitmentTrendChart
              trend={data.trend}
              conversions={data.conversions}
              totals={data.team_table?.totals ?? null}
            />

            {/* Rywalizacje — własne okresy biznesowe (kwartał/miesiąc/all-time) */}
            <RecruitmentCompetitions
              league={data.quarterly_league}
              races={data.monthly_races}
              hallOfFame={data.hall_of_fame}
              highlightUserId={user?.id ?? null}
            />

            {/* LinkedIn Performance — okres sekcji */}
            {data.linkedin ? (
              <RecruitmentLinkedInPanel linkedin={data.linkedin} />
            ) : (
              <div className="rounded-xl border border-dashed border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground">
                LinkedIn: dane chwilowo niedostępne (to NIE jest zero).
              </div>
            )}
          </div>
        ) : null}
      </StatsBoundary>
    </section>
  )
}

export default RecruitmentStatsSection
