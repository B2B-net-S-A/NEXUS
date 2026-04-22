"use client"

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  Legend,
} from "recharts"
import {
  Briefcase,
  ChevronDown,
  ChevronUp,
  Crown,
  Target,
  TrendingUp,
  Users,
} from "lucide-react"

import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ChampionsPodium } from "@/components/v2/gamification/ChampionsPodium"
import { useAuthStore } from "@/store/auth"

// ── Types ────────────────────────────────────────────────────────────────

interface DlRow {
  user_id: number
  name: string
  total_requests: number
  total_vacancies: number
  placements: number
  hit_ratio: number
  fill_rate: number
  avg_vacancies_per_request: number
  open_requests: number
  open_vacancies: number
  target_achieved: boolean
  clients: string[]
}

interface MyDlResponse {
  period: string
  me: DlRow
  rank: number | null
  total_dls: number
  team_overall: {
    total_requests: number
    total_vacancies: number
    total_placements: number
    total_open_requests: number
    total_open_vacancies: number
    avg_hit_ratio: number
    avg_fill_rate: number
    target_count: number
    dl_count: number
    hit_ratio_target_pct: number
  }
  leaderboard_top5: DlRow[]
}

interface DlReportResponse {
  period: string
  per_dl: DlRow[]
  overall: MyDlResponse["team_overall"]
}

interface TrendPoint {
  month: string
  month_label: string
  requests: number
  vacancies: number
  placements: number
  hit_ratio: number
  fill_rate: number
}

interface TrendResponse {
  dl_id: number
  months: number
  trend: TrendPoint[]
}

interface CompetitionResponse {
  type: string
  period: string
  top3: Array<{
    rank: number
    user_id: number
    name: string
    metric_value: number
    hit_ratio?: number | null
    prize_pln?: number
  }>
  target_pct?: number | null
}

// ── KPI Card ─────────────────────────────────────────────────────────────

function KpiCard({
  title,
  value,
  subtitle,
  accent,
  icon: Icon,
}: {
  title: string
  value: React.ReactNode
  subtitle?: string
  accent?: "default" | "green" | "amber"
  icon: React.ComponentType<{ className?: string }>
}) {
  const accentClass =
    accent === "green"
      ? "text-[#1d5e31]"
      : accent === "amber"
      ? "text-amber-600"
      : "text-[hsl(var(--text-title))]"
  return (
    <Card>
      <div className="flex items-start justify-between gap-2 mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))]">
          {title}
        </p>
        <span className="inline-flex items-center justify-center h-8 w-8 rounded-v2-s bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]">
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div
        className={cn(
          "font-display text-3xl font-extrabold tracking-[-0.02em] leading-none",
          accentClass,
        )}
      >
        {value}
      </div>
      {subtitle && (
        <p className="text-xs text-[hsl(var(--text-muted))] mt-2">{subtitle}</p>
      )}
    </Card>
  )
}

// ── Ranking Table ────────────────────────────────────────────────────────

type SortKey =
  | "placements"
  | "total_requests"
  | "total_vacancies"
  | "hit_ratio"
  | "fill_rate"
  | "name"

function DlRankingTable({
  rows,
  highlightUserId,
  targetPct,
}: {
  rows: DlRow[]
  highlightUserId?: number | null
  targetPct: number
}) {
  const [sortBy, setSortBy] = useMemo(() => ["placements", "desc"] as const, [])
  const sorted = [...rows].sort((a, b) => {
    const va = a[sortBy[0] as keyof DlRow]
    const vb = b[sortBy[0] as keyof DlRow]
    if (typeof va === "string" && typeof vb === "string") {
      return sortBy[1] === "asc" ? va.localeCompare(vb) : vb.localeCompare(va)
    }
    const na = Number(va) || 0
    const nb = Number(vb) || 0
    return sortBy[1] === "asc" ? na - nb : nb - na
  })

  const Header = ({ col, label }: { col: SortKey; label: string }) => (
    <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2">
      <span className="inline-flex items-center gap-1">
        {label}
        {sortBy[0] === col &&
          (sortBy[1] === "asc" ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          ))}
      </span>
    </th>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-[hsl(var(--border-subtle))]">
          <tr>
            <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-[hsl(var(--text-muted))] px-3 py-2 w-12">
              #
            </th>
            <Header col="name" label="Delivery Lead" />
            <Header col="total_requests" label="Requests" />
            <Header col="total_vacancies" label="Vacancies" />
            <Header col="placements" label="Placements" />
            <Header col="hit_ratio" label="Hit %" />
            <Header col="fill_rate" label="Fill %" />
          </tr>
        </thead>
        <tbody className="divide-y divide-[hsl(var(--border-subtle))]">
          {sorted.map((r, idx) => {
            const isMe = highlightUserId === r.user_id
            return (
              <tr
                key={r.user_id}
                className={cn(
                  "hover:bg-[hsl(var(--accent-soft))]/40 transition-colors",
                  isMe && "bg-[hsl(var(--accent-soft))]/60",
                  r.target_achieved &&
                    !isMe &&
                    "bg-emerald-50/40",
                )}
              >
                <td className="px-3 py-2 text-[hsl(var(--text-muted))] font-bold">
                  {idx + 1}
                </td>
                <td className="px-3 py-2 font-medium text-[hsl(var(--text-title))]">
                  <span className="inline-flex items-center gap-1.5">
                    {r.name}
                    {isMe && (
                      <Badge variant="soft" size="sm">
                        Ja
                      </Badge>
                    )}
                    {r.target_achieved && (
                      <Crown
                        className="h-3.5 w-3.5 text-amber-500"
                        aria-label={`≥${targetPct}% hit ratio`}
                      />
                    )}
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums">{r.total_requests}</td>
                <td className="px-3 py-2 tabular-nums">{r.total_vacancies}</td>
                <td className="px-3 py-2 tabular-nums font-semibold">
                  {r.placements}
                </td>
                <td className="px-3 py-2 tabular-nums">
                  <span
                    className={cn(
                      r.hit_ratio >= targetPct
                        ? "text-[#1d5e31] font-semibold"
                        : "text-[hsl(var(--text-muted))]",
                    )}
                  >
                    {r.hit_ratio.toFixed(1)}%
                  </span>
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {r.fill_rate.toFixed(1)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <p className="text-center text-sm text-[hsl(var(--text-muted))] py-6">
          Brak danych w tym okresie.
        </p>
      )}
    </div>
  )
}

// ── Trend Chart ──────────────────────────────────────────────────────────

function TrendChart({ trend }: { trend: TrendPoint[] }) {
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={trend} margin={{ top: 10, right: 20, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border-subtle))" />
          <XAxis
            dataKey="month_label"
            tick={{ fontSize: 11 }}
            stroke="hsl(var(--text-muted))"
          />
          <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--text-muted))" />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="requests"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Requests"
          />
          <Line
            type="monotone"
            dataKey="placements"
            stroke="#1d5e31"
            strokeWidth={2}
            dot={{ r: 3 }}
            name="Placements"
          />
          <Line
            type="monotone"
            dataKey="hit_ratio"
            stroke="#b45309"
            strokeWidth={2}
            dot={{ r: 3 }}
            strokeDasharray="4 4"
            name="Hit Ratio %"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────

export default function DeliveryLeadDashboard() {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  const { data: me, isLoading: meLoading } = useQuery<MyDlResponse>({
    queryKey: ["my-delivery-lead", "month"],
    queryFn: () =>
      api
        .get("/api/reports/my-delivery-lead?period=month")
        .then((r) => r.data),
    enabled: hydrated && user?.role === "delivery_lead",
    staleTime: 60 * 1000,
  })

  const { data: teamReport } = useQuery<DlReportResponse>({
    queryKey: ["report-delivery-leads", "month"],
    queryFn: () =>
      api.get("/api/reports/delivery-leads?period=month").then((r) => r.data),
    enabled: hydrated && !!user,
    staleTime: 5 * 60 * 1000,
  })

  const { data: trend } = useQuery<TrendResponse>({
    queryKey: ["delivery-lead-trend", user?.id],
    queryFn: () =>
      api
        .get(`/api/reports/delivery-leads/${user?.id}/trend?months=6`)
        .then((r) => r.data),
    enabled: hydrated && !!user && user.role === "delivery_lead",
    staleTime: 5 * 60 * 1000,
  })

  const { data: champions } = useQuery<CompetitionResponse>({
    queryKey: ["competitions-current", "quarterly_champions_dl"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_dl")
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (!hydrated) {
    return <div className="p-6 text-[hsl(var(--text-muted))]">Ładowanie…</div>
  }

  if (!user || user.role !== "delivery_lead") {
    return (
      <div className="p-6">
        <Card>
          <CardHeader>
            <CardTitle>Brak dostępu</CardTitle>
            <CardDescription>
              Ten panel jest dostępny tylko dla roli Delivery Lead. Admini
              mogą podejrzeć dane na /reports.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const myRow = me?.me
  const clientsCount = myRow?.clients.length ?? 0
  const targetPct = me?.team_overall.hit_ratio_target_pct ?? 30

  return (
    <div className="max-w-[1400px] mx-auto space-y-6 p-4 md:p-6">
      {/* Hero */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
          Panel Delivery Lead · {new Date().toLocaleDateString("pl-PL", { month: "long", year: "numeric" })}
        </p>
        <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-[hsl(var(--text-title))] mt-1">
          Cześć, {user.name.split(" ")[0]}
        </h1>
        <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
          Twoje body leasing w liczbach + miejsce w Lidze Mistrzów.
        </p>
      </div>

      {/* KPI cards */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {meLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-4 bg-[hsl(var(--border-subtle))] rounded w-24 mb-3" />
              <div className="h-8 bg-[hsl(var(--border-subtle))] rounded w-20" />
            </Card>
          ))
        ) : (
          <>
            <KpiCard
              title="Requests (body leasing)"
              value={myRow?.total_requests ?? 0}
              subtitle={`${myRow?.total_vacancies ?? 0} vacancy`}
              icon={Briefcase}
            />
            <KpiCard
              title="Placements"
              value={myRow?.placements ?? 0}
              subtitle={`pozycja #${me?.rank ?? "—"} / ${me?.total_dls ?? 0}`}
              icon={Target}
              accent="green"
            />
            <KpiCard
              title="Hit Ratio"
              value={`${(myRow?.hit_ratio ?? 0).toFixed(1)}%`}
              subtitle={
                myRow?.target_achieved
                  ? `cel ≥${targetPct}% osiągnięty`
                  : `do celu brakuje ${Math.max(targetPct - (myRow?.hit_ratio ?? 0), 0).toFixed(1)} pp`
              }
              accent={myRow?.target_achieved ? "green" : "amber"}
              icon={TrendingUp}
            />
            <KpiCard
              title="Fill Rate"
              value={`${(myRow?.fill_rate ?? 0).toFixed(1)}%`}
              subtitle={`avg ${(myRow?.avg_vacancies_per_request ?? 0).toFixed(2)} vacancy/req`}
              icon={Users}
            />
          </>
        )}
      </section>

      {/* Moi klienci + Pipeline otwarty */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Crown className="h-4 w-4 text-amber-500" />
              <CardTitle>Moi klienci</CardTitle>
              <span className="ml-auto text-xs text-[hsl(var(--text-muted))]">
                {clientsCount} aktywnych
              </span>
            </div>
          </CardHeader>
          <CardContent>
            {clientsCount === 0 ? (
              <p className="text-sm text-[hsl(var(--text-muted))] py-4">
                Nie masz przypisanych klientów. Skontaktuj się z Head of
                Recruitment żeby dopisać Cię w panelu macierzy.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {myRow?.clients.map((c) => (
                  <Badge key={c} variant="soft">
                    {c}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Otwarty pipeline</CardTitle>
            <CardDescription>pokazuje potencjał do zrealizowania</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-[hsl(var(--text-body))]">
                Otwarte requesty
              </span>
              <span className="font-display text-2xl font-extrabold text-[hsl(var(--text-title))]">
                {myRow?.open_requests ?? 0}
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-[hsl(var(--text-body))]">
                Otwarte vacancy
              </span>
              <span className="font-display text-2xl font-extrabold text-[hsl(var(--accent))]">
                {myRow?.open_vacancies ?? 0}
              </span>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Trend 6M + Podium */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[hsl(var(--accent))]" />
              <CardTitle>Mój trend 6 miesięcy</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            {trend && trend.trend.length > 0 ? (
              <TrendChart trend={trend.trend} />
            ) : (
              <p className="text-sm text-[hsl(var(--text-muted))] py-8 text-center">
                Brak danych historycznych.
              </p>
            )}
          </CardContent>
        </Card>

        <ChampionsPodium
          title="Liga Mistrzów DL"
          subtitle="Kwartalny ranking"
          period={champions?.period ?? ""}
          top3={champions?.top3 ?? []}
          metricLabel="placementów"
          targetPct={champions?.target_pct ?? 30}
          highlightUserId={user.id}
        />
      </section>

      {/* Ranking DL zespołu */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[hsl(var(--accent))]" />
            <CardTitle>Ranking zespołu Delivery Leadów</CardTitle>
            <Badge variant="soft" size="sm" className="ml-auto">
              bieżący miesiąc
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <DlRankingTable
            rows={teamReport?.per_dl ?? []}
            highlightUserId={user.id}
            targetPct={targetPct}
          />
        </CardContent>
      </Card>
    </div>
  )
}
