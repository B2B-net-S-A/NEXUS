"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  BriefcaseBusiness,
  Building2,
  CircleDollarSign,
  Clock3,
  Gauge,
  HeartPulse,
  ListChecks,
  ShieldAlert,
  Target,
  Users,
} from "lucide-react"

import { StatCard, StatCardGrid } from "@/components/ds"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  StatsBoundary,
  type StatsBoundaryState,
} from "@/components/v2/dashboard/StatsBoundary"
import {
  getDashboardV2,
  type DashboardAlert,
  type DashboardKpi,
  type DashboardQueueItem,
  type DashboardV2ResponseMap,
  type FinanceDashboardTab,
} from "@/lib/dashboard-v2-api"
import {
  getAvailableDashboardPresets,
  type DashboardPeriod,
  type DashboardPreset,
} from "@/lib/dashboard-presets"
import { useAuthStore } from "@/store/auth"

const KPI_CONFIG: Record<
  DashboardPreset,
  Array<{
    metric: string
    label: string
    icon: typeof Target
  }>
> = {
  "admin-ops": [
    { metric: "critical_readiness", label: "Readiness", icon: HeartPulse },
    { metric: "critical_schema_drift", label: "Krytyczny drift", icon: ShieldAlert },
    { metric: "background_workers", label: "Workery", icon: Gauge },
    { metric: "failed_dead_events", label: "Failed / dead", icon: AlertTriangle },
  ],
  "delivery-lead": [
    { metric: "open_requests", label: "Otwarte requesty", icon: ListChecks },
    { metric: "open_vacancies", label: "Otwarte wakaty", icon: BriefcaseBusiness },
    {
      metric: "first_recommendation_sla_pct",
      label: "Pierwsza rekomendacja w SLA",
      icon: Clock3,
    },
    { metric: "placements", label: "Placementy", icon: Target },
  ],
  "head-of-recruitment": [
    { metric: "priority_vacancies", label: "Priorytetowe wakaty", icon: Target },
    { metric: "unassigned_work", label: "Nieprzypisana praca", icon: ListChecks },
    {
      metric: "capacity_utilization_pct",
      label: "Wykorzystanie capacity",
      icon: Gauge,
    },
    { metric: "placements", label: "Placementy", icon: Users },
  ],
  "my-work": [
    { metric: "plan_completion_pct", label: "Realizacja planu", icon: Gauge },
    { metric: "overdue_actions", label: "Zaległe działania", icon: Clock3 },
    { metric: "completed_calls", label: "Rozmowy", icon: ListChecks },
    { metric: "first_verifications", label: "Weryfikacje", icon: Target },
  ],
  finance: [
    { metric: "mrr_pln", label: "MRR", icon: CircleDollarSign },
    { metric: "monthly_margin_pln", label: "Marża / mies.", icon: Gauge },
    { metric: "outstanding_pln", label: "Należności", icon: Building2 },
    { metric: "overdue_pln", label: "Po terminie", icon: AlertTriangle },
  ],
}

const EXECUTIVE_FINANCE_KPIS = [
  { metric: "mrr_pln", label: "MRR", icon: CircleDollarSign },
  { metric: "monthly_margin_pln", label: "Marża / mies.", icon: Gauge },
  {
    metric: "revenue_forecast_3m_pln",
    label: "Prognoza 3M",
    icon: Target,
  },
  { metric: "mrr_at_risk_90d_pln", label: "MRR at risk", icon: AlertTriangle },
]

function formatKpi(kpi: DashboardKpi | undefined): string | number {
  if (!kpi || kpi.quality === "unavailable" || kpi.value == null) return "—"
  if (kpi.unit === "percent") return `${kpi.value}%`
  if (kpi.unit === "hours") return `${kpi.value} h`
  if (kpi.unit === "PLN") return `${kpi.value} PLN`
  return kpi.value
}

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

function SeverityBadge({ severity }: { severity: DashboardAlert["severity"] }) {
  const variant =
    severity === "critical"
      ? "danger"
      : severity === "warning"
        ? "warning"
        : "neutral"
  return (
    <Badge variant={variant} size="sm">
      {severity}
    </Badge>
  )
}

function QueueList({ items }: { items: DashboardQueueItem[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Kolejka działań</CardTitle>
        <CardDescription>Najwyższy priorytet jest zawsze pierwszy.</CardDescription>
      </CardHeader>
      <CardContent>
        {items.length ? (
          <ol className="divide-y divide-border">
            {items.slice(0, 8).map((item) => {
              const body = (
                <div className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {item.title}
                    </p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {item.subtitle ?? item.source}
                    </p>
                  </div>
                  <Badge
                    variant={item.priority >= 90 ? "danger" : "neutral"}
                    size="sm"
                  >
                    P{item.priority}
                  </Badge>
                </div>
              )
              return (
                <li key={item.id}>
                  {item.href ? (
                    <Link
                      href={item.href}
                      className="block rounded-md hover:bg-muted/50 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {body}
                    </Link>
                  ) : (
                    body
                  )}
                </li>
              )
            })}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">
            Brak działań wymagających reakcji.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function AlertsList({ alerts }: { alerts: DashboardAlert[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Alerty</CardTitle>
        <CardDescription>
          Sygnały jakości i ryzyka z autoryzowanego zakresu danych.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {alerts.length ? (
          <ul className="space-y-3">
            {alerts.slice(0, 8).map((alert) => (
              <li
                key={alert.id}
                className="rounded-lg border border-border bg-muted/30 p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    {alert.href ? (
                      <Link
                        href={alert.href}
                        className="text-sm font-medium text-foreground hover:text-primary"
                      >
                        {alert.title}
                      </Link>
                    ) : (
                      <p className="text-sm font-medium text-foreground">
                        {alert.title}
                      </p>
                    )}
                    {alert.description ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {alert.description}
                      </p>
                    ) : null}
                  </div>
                  <SeverityBadge severity={alert.severity} />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Brak aktywnych alertów.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function Board({
  preset,
  response,
}: {
  preset: DashboardPreset
  response: DashboardV2ResponseMap[DashboardPreset]
}) {
  const data = response.data
  let headers: string[] = []
  let rows: Array<{ id: string; cells: Array<string | number>; href?: string }> =
    []

  if ("operations_board" in data) {
    headers = ["Domena", "Sygnał", "Poziom", "Owner"]
    rows = data.operations_board.map((row) => ({
      id: row.id,
      cells: [row.domain, row.signal, row.severity, row.owner ?? "—"],
      href: row.next_action_href ?? undefined,
    }))
  } else if ("risk_board" in data) {
    headers = ["Klient", "Proces", "Wakaty", "Wiek", "Ryzyko"]
    rows = data.risk_board.map((row) => ({
      id: String(row.job_id),
      cells: [
        row.client_name,
        row.job_title,
        row.open_vacancies,
        `${row.age_days} dni`,
        row.risk,
      ],
      href: row.next_action_href,
    }))
  } else if ("team_board" in data) {
    headers = ["Osoba", "Status", "Target / capacity", "Carry-over", "Blockery"]
    rows = data.team_board.map((row) => ({
      id: String(row.user_id),
      cells: [
        row.user_name,
        row.status,
        `${row.verification_target} / ${row.verification_capacity}`,
        row.carry_over_count,
        row.blocker_count,
      ],
    }))
  } else if ("exceptions_board" in data) {
    headers = ["Typ", "Klient", "Dokument", "Kwota", "Poziom"]
    rows = data.exceptions_board.map((row) => ({
      id: row.id,
      cells: [
        row.kind,
        row.client_name ?? "—",
        row.invoice_number ?? (row.contract_id ? `#${row.contract_id}` : "—"),
        row.amount ? `${row.amount} ${row.currency ?? ""}`.trim() : "—",
        row.severity,
      ],
      href: row.next_action_href ?? undefined,
    }))
  }

  if (!rows.length || preset === "my-work") return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Widok roboczy</CardTitle>
        <CardDescription>
          Rekordy są ograniczone przez scope zwrócony w tej samej odpowiedzi.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              {headers.map((header) => (
                <th key={header} className="px-3 py-2 font-medium">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.slice(0, 12).map((row) => (
              <tr key={row.id} className="hover:bg-muted/40">
                {row.cells.map((cell, index) => (
                  <td key={`${row.id}-${index}`} className="px-3 py-3">
                    {index === 0 && row.href ? (
                      <Link
                        href={row.href}
                        className="font-medium text-foreground hover:text-primary"
                      >
                        {cell}
                      </Link>
                    ) : (
                      cell
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

export function DashboardV2Preset({
  preset,
  period,
  financeTab,
}: {
  preset: DashboardPreset
  period: DashboardPeriod
  financeTab?: FinanceDashboardTab
}) {
  const user = useAuthStore((state) => state.user)
  const allowed = getAvailableDashboardPresets(user).includes(preset)
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
          (a, b) =>
            a.client_id - b.client_id || a.tac_user_id - b.tac_user_id,
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
      "dashboard-v2",
      preset,
      period,
      financeTab ?? null,
      user?.id ?? null,
      user?.authorization_version ?? null,
      scopeCacheKey,
      capabilityCacheKey,
    ],
    queryFn: () => getDashboardV2(preset, { period, financeTab }),
    enabled: Boolean(user) && allowed,
    staleTime: 60_000,
  })
  const state = allowed
    ? boundaryState(query, query.data?.data_quality)
    : "forbidden"

  const kpiConfig =
    preset === "finance" && financeTab === "executive"
      ? EXECUTIVE_FINANCE_KPIS
      : KPI_CONFIG[preset]
  const kpis = query.data?.data.kpis as
    | Record<string, DashboardKpi>
    | undefined

  return (
    <StatsBoundary
      state={state}
      warnings={query.data?.data_quality.warnings}
      onRetry={() => query.refetch()}
    >
      {query.data ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Scope: {query.data.scope.kind}
            </p>
            <Badge variant="neutral" size="sm">
              schema v{query.data.schema_version}
            </Badge>
          </div>

          <StatCardGrid>
            {kpiConfig.map(({ metric, label, icon }) => {
              const kpi = kpis?.[metric]
              return (
                <StatCard
                  key={metric}
                  label={label}
                  value={formatKpi(kpi)}
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

          <div className="grid gap-4 xl:grid-cols-2">
            <QueueList items={query.data.data.queue} />
            <AlertsList alerts={query.data.data.alerts} />
          </div>

          <Board preset={preset} response={query.data} />
        </div>
      ) : null}
    </StatsBoundary>
  )
}
