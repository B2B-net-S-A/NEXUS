"use client"

import { useMemo, useState } from"react"
import { useQuery } from"@tanstack/react-query"
import {
 Briefcase,
 ChevronDown,
 ChevronUp,
 Crown,
 LineChart as LineIcon,
 RefreshCw,
 Target,
 TrendingUp,
 Users,
} from"lucide-react"
import {
 Bar,
 BarChart,
 CartesianGrid,
 Legend,
 Line,
 LineChart,
 ResponsiveContainer,
 Tooltip,
 XAxis,
 YAxis,
} from"recharts"

import api from"@/lib/api"
import { cn } from"@/lib/utils"
import { Badge } from"@/components/ui/badge"
import { Button } from"@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card"
import { HeroLigaMistrzow, type HeroPodiumEntry } from"@/components/v2/gamification/HeroLigaMistrzow"
import { useAuthStore } from"@/store/auth"

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

interface DlReport {
 period: string
 per_dl: DlRow[]
 overall: {
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

interface CompetitionResponse {
 type: string
 period: string
 top3: HeroPodiumEntry[]
 full_ranking: HeroPodiumEntry[]
 days_remaining: number | null
 quarterly_prizes_pln: Record<string, number> | null
 requirement: string | null
 target_pct: number | null
}

interface DlClientsSummary {
 delivery_lead: { id: number; name: string }
 clients: Array<{ id: number; name: string; is_head: boolean }>
}

// ── Pastel KPI (same as recruiter) ─────────────────────────────────────

const KPI_COLORS = {
 slate: {
 bg: "bg-slate-50 border-slate-200",
 icon: "bg-slate-100 text-slate-700",
 title: "text-slate-900",
 value: "text-slate-950",
 },
 amber: {
 bg: "bg-amber-50 border-amber-200",
 icon: "bg-amber-100 text-amber-700",
 title: "text-amber-900",
 value: "text-amber-950",
 },
 purple: {
 bg: "bg-purple-50 border-purple-200",
 icon: "bg-purple-100 text-purple-700",
 title: "text-purple-900",
 value: "text-purple-950",
 },
 emerald: {
 bg: "bg-emerald-50 border-emerald-200",
 icon: "bg-emerald-100 text-emerald-700",
 title: "text-emerald-900",
 value: "text-emerald-950",
 },
} as const

function PastelKpi({
 title,
 value,
 subtitle,
 icon: Icon,
 color,
}: {
 title: string
 value: React.ReactNode
 subtitle?: string
 icon: React.ComponentType<{ className?: string }>
 color: keyof typeof KPI_COLORS
}) {
 const c = KPI_COLORS[color]
 return (
 <div className={cn("rounded-lg border px-4 py-3", c.bg)}>
 <div className="flex items-center gap-2 mb-2">
 <span
 className={cn("inline-flex items-center justify-center h-7 w-7 rounded-full",
 c.icon,
 )}
 >
 <Icon className="h-4 w-4" />
 </span>
 <span className={cn("text-[11px] font-semibold uppercase tracking-wide", c.title)}>
 {title}
 </span>
 </div>
 <div className={cn("font-semibold text-3xl font-extrabold leading-none", c.value)}>
 {value}
 </div>
 {subtitle && (
 <div className={cn("text-xs mt-1.5 opacity-80", c.title)}>{subtitle}</div>
 )}
 </div>
 )
}

// ── Hit ratio color helper ──────────────────────────────────────────────

function hitRatioColor(value: number, target: number): string {
 if (value >= target) return"text-emerald-600 font-semibold"
 if (value >= target * 0.66) return"text-amber-600 font-medium"
 return"text-rose-600"
}

function fillRateColor(value: number): string {
 if (value >= 30) return"text-emerald-600 font-semibold"
 if (value >= 15) return"text-amber-600 font-medium"
 return"text-rose-600"
}

// ── Ranking table ───────────────────────────────────────────────────────

type SortKey =
 |"placements"
 |"total_requests"
 |"total_vacancies"
 |"hit_ratio"
 |"fill_rate"
 |"name"

function DlRanking({
 rows,
 highlightUserId,
 targetPct,
}: {
 rows: DlRow[]
 highlightUserId?: number | null
 targetPct: number
}) {
 const [sortBy, setSortBy] = useState<SortKey>("placements")
 const [sortDir, setSortDir] = useState<"asc" |"desc">("desc")

 const sorted = useMemo(() => {
 const data = [...rows]
 data.sort((a, b) => {
 const va = a[sortBy] as number | string
 const vb = b[sortBy] as number | string
 if (typeof va ==="string" && typeof vb ==="string") {
 return sortDir ==="asc" ? va.localeCompare(vb) : vb.localeCompare(va)
 }
 const na = Number(va) || 0
 const nb = Number(vb) || 0
 return sortDir ==="asc" ? na - nb : nb - na
 })
 return data
 }, [rows, sortBy, sortDir])

 function toggleSort(key: SortKey) {
 if (sortBy === key) {
 setSortDir(sortDir ==="asc" ?"desc" :"asc")
 } else {
 setSortBy(key)
 setSortDir("desc")
 }
 }

 const Header = ({ col, label }: { col: SortKey; label: string }) => (
 <th
 className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 cursor-pointer select-none"
 onClick={() => toggleSort(col)}
 >
 <span className="inline-flex items-center gap-1">
 {label}
 {sortBy === col &&
 (sortDir ==="asc" ? (
 <ChevronUp className="h-3 w-3" />
 ) : (
 <ChevronDown className="h-3 w-3" />
 ))}
 </span>
 </th>
 )

 const rankBadge = (idx: number): string => {
 if (idx === 0) return"bg-emerald-500 text-white"
 if (idx === 1) return"bg-sky-500 text-white"
 if (idx === 2) return"bg-amber-500 text-white"
 return"bg-slate-200 text-slate-700"
 }

 return (
 <div className="overflow-x-auto">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 w-12">
 #
 </th>
 <Header col="name" label="Delivery Lead" />
 <Header col="total_requests" label="Zapytania" />
 <Header col="total_vacancies" label="Wakaty" />
 <Header col="placements" label="Placements" />
 <Header col="hit_ratio" label="Hit Ratio" />
 <Header col="fill_rate" label="Fill Rate" />
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {sorted.map((r, idx) => {
 const isMe = highlightUserId === r.user_id
 return (
 <tr
 key={r.user_id}
 className={cn("hover:bg-primary/10/40",
 isMe &&"bg-primary/10/60",
 )}
 >
 <td className="px-3 py-2">
 <span
 className={cn("inline-flex items-center justify-center h-6 w-6 rounded-full text-xs font-bold",
 rankBadge(idx),
 )}
 >
 {idx + 1}
 </span>
 </td>
 <td className="px-3 py-2 font-medium text-foreground">
 {r.name}
 {isMe && (
 <Badge variant="soft" size="sm" className="ml-2">
 Ja
 </Badge>
 )}
 {r.target_achieved && (
 <Crown
 className="inline h-3.5 w-3.5 ml-1.5 text-amber-500"
 aria-label={`hit ratio ≥ ${targetPct}%`}
 />
 )}
 </td>
 <td className="px-3 py-2 tabular-nums">{r.total_requests}</td>
 <td className="px-3 py-2 tabular-nums text-sky-600">
 {r.total_vacancies}
 </td>
 <td className="px-3 py-2 tabular-nums font-semibold">
 {r.placements}
 </td>
 <td
 className={cn("px-3 py-2 tabular-nums",
 hitRatioColor(r.hit_ratio, targetPct),
 )}
 >
 {r.hit_ratio.toFixed(1)}%
 </td>
 <td
 className={cn("px-3 py-2 tabular-nums",
 fillRateColor(r.fill_rate),
 )}
 >
 {r.fill_rate.toFixed(1)}%
 </td>
 </tr>
 )
 })}
 </tbody>
 </table>
 {sorted.length === 0 && (
 <p className="text-center text-sm text-muted-foreground py-6">
 Brak danych w tym okresie.
 </p>
 )}
 </div>
 )
}

// ── Team history chart (5 serii) ────────────────────────────────────────

function TeamHistoryChart({
 trend,
 type,
}: {
 trend: TrendPoint[]
 type: "line" |"bar"
}) {
 const Chart = type ==="line" ? LineChart : BarChart
 return (
 <div className="h-80">
 <ResponsiveContainer width="100%" height="100%">
 <Chart
 data={trend}
 margin={{ top: 10, right: 20, bottom: 0, left: -10 }}
 >
 <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
 <XAxis
 dataKey="month_label"
 tick={{ fontSize: 11 }}
 stroke="hsl(var(--muted-foreground))"
 />
 <YAxis
 yAxisId="left"
 tick={{ fontSize: 11 }}
 stroke="hsl(var(--muted-foreground))"
 />
 <YAxis
 yAxisId="right"
 orientation="right"
 tick={{ fontSize: 11 }}
 stroke="hsl(var(--muted-foreground))"
 />
 <Tooltip />
 <Legend wrapperStyle={{ fontSize: 12 }} />
 {type ==="line" ? (
 <>
 <Line
 yAxisId="left"
 type="monotone"
 dataKey="requests"
 stroke="#0ea5e9"
 name="Zapytania"
 />
 <Line
 yAxisId="left"
 type="monotone"
 dataKey="vacancies"
 stroke="#8b5cf6"
 name="Wakaty"
 />
 <Line
 yAxisId="left"
 type="monotone"
 dataKey="placements"
 stroke="#10b981"
 name="Placements"
 />
 <Line
 yAxisId="right"
 type="monotone"
 dataKey="hit_ratio"
 stroke="#f59e0b"
 strokeDasharray="4 4"
 name="Hit Ratio %"
 />
 <Line
 yAxisId="right"
 type="monotone"
 dataKey="fill_rate"
 stroke="#ec4899"
 strokeDasharray="4 4"
 name="Fill Rate %"
 />
 </>
 ) : (
 <>
 <Bar yAxisId="left" dataKey="requests" fill="#0ea5e9" name="Zapytania" />
 <Bar yAxisId="left" dataKey="vacancies" fill="#8b5cf6" name="Wakaty" />
 <Bar
 yAxisId="left"
 dataKey="placements"
 fill="#10b981"
 name="Placements"
 />
 </>
 )}
 </Chart>
 </ResponsiveContainer>
 </div>
 )
}

// ── Main Page ───────────────────────────────────────────────────────────

export default function DeliveryLeadDashboard() {
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)

 // Allow DL + admin + HoR (team-wide view).
 const isAllowed =
 !!user &&
 ["delivery_lead","admin","head_of_recruitment"].includes(user.role)
 const isMeDl = user?.role ==="delivery_lead"

 const [chartType, setChartType] = useState<"line" |"bar">("line")

 const { data: teamReport, refetch: refetchReport } = useQuery<DlReport>({
 queryKey: ["report-delivery-leads","month"],
 queryFn: () =>
 api.get("/api/reports/delivery-leads?period=month").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const { data: trendAll } = useQuery<{ trend: TrendPoint[] } | null>({
 queryKey: ["dl-trend-all","6m"],
 // Nexus nie ma (jeszcze) team-wide trendu; używamy trendu zalogowanego DL
 // jako proxy. Dla admina/HoR zwróci null (endpoint wymaga dl_id).
 queryFn: async () => {
 if (!user || user.role !=="delivery_lead") return null
 const r = await api.get(
 `/api/reports/delivery-leads/${user.id}/trend?months=6`,
 )
 return r.data
 },
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const { data: champions, refetch: refetchQ } = useQuery<CompetitionResponse>({
 queryKey: ["competitions-current","quarterly_champions_dl"],
 queryFn: () =>
 api
 .get("/api/competitions/current?type=quarterly_champions_dl")
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const { data: dlClients } = useQuery<DlClientsSummary[]>({
 queryKey: ["team-structure-dl-clients"],
 queryFn: () =>
 api.get("/api/team-structure/dl-clients").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 if (!hydrated) {
 return <div className="p-6 text-muted-foreground">Ładowanie…</div>
 }

 if (!isAllowed) {
 return (
 <div className="p-6">
 <Card>
 <CardHeader>
 <CardTitle>Brak dostępu</CardTitle>
 <CardDescription>
 Panel dla ról: Delivery Lead, Admin, Head of Recruitment.
 </CardDescription>
 </CardHeader>
 </Card>
 </div>
 )
 }

 const ov = teamReport?.overall
 const targetPct = ov?.hit_ratio_target_pct ?? 30

 return (
 <div className="max-w-[1400px] mx-auto space-y-5 p-4 md:p-6">
 {/* Header */}
 <div className="flex items-start justify-between flex-wrap gap-3">
 <div className="flex items-center gap-3">
 <div className="h-12 w-12 rounded-lg bg-amber-500 flex items-center justify-center shadow">
 <Target className="h-7 w-7 text-white" />
 </div>
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Panel Delivery Lead
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground leading-tight">
 Hit Ratio i Placements
 </h1>
 </div>
 </div>
 <Button
 variant="outline"
 size="sm"
 onClick={() => {
 refetchReport()
 refetchQ()
 }}
 >
 <RefreshCw className="h-4 w-4" />
 Odśwież
 </Button>
 </div>

 {/* KPI row */}
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
 <PastelKpi
 title="Zamknięte zapytania"
 value={ov?.total_requests ?? 0}
 subtitle={`+${ov?.total_open_requests ?? 0} otwartych`}
 icon={Briefcase}
 color="slate"
 />
 <PastelKpi
 title="Placements"
 value={ov?.total_placements ?? 0}
 subtitle={`${ov?.total_vacancies ?? 0} wakatów łącznie`}
 icon={Target}
 color="amber"
 />
 <PastelKpi
 title="Średni Hit Ratio"
 value={`${(ov?.avg_hit_ratio ?? 0).toFixed(1)}%`}
 subtitle={`cel: ${targetPct}%`}
 icon={TrendingUp}
 color="purple"
 />
 <PastelKpi
 title={`Osiąga target (${targetPct}%)`}
 value={
 <>
 {ov?.target_count ?? 0}
 <span className="text-muted-foreground text-2xl">
 /{ov?.dl_count ?? 0}
 </span>
 </>
 }
 subtitle={`Fill Rate śr.: ${(ov?.avg_fill_rate ?? 0).toFixed(1)}%`}
 icon={Users}
 color="emerald"
 />
 </div>

 {/* Hero Liga Mistrzów DL */}
 {champions && (
 <HeroLigaMistrzow
 title="Liga Mistrzów DL"
 period={champions.period}
 daysRemaining={champions.days_remaining ?? 0}
 top3={champions.top3}
 fullRanking={champions.full_ranking}
 quarterlyPrizes={
 champions.quarterly_prizes_pln
 ? Object.fromEntries(
 Object.entries(champions.quarterly_prizes_pln).map(
 ([k, v]) => [Number(k), v],
 ),
 )
 : { 1: 5000, 2: 3000, 3: 2000 }
 }
 metricLabel="placementów"
 metricUnit=""
 requirement={champions.requirement}
 highlightUserId={isMeDl ? user?.id : null}
 />
 )}

 {/* Historia zespołu */}
 {isMeDl && trendAll?.trend && trendAll.trend.length > 0 && (
 <Card>
 <CardHeader>
 <div className="flex items-center gap-2">
 <LineIcon className="h-4 w-4 text-primary" />
 <CardTitle>Moja historia 6 miesięcy</CardTitle>
 <div className="ml-auto flex gap-1">
 <Button
 variant={chartType ==="line" ?"primary" :"outline"}
 size="sm"
 onClick={() => setChartType("line")}
 >
 Liniowy
 </Button>
 <Button
 variant={chartType ==="bar" ?"primary" :"outline"}
 size="sm"
 onClick={() => setChartType("bar")}
 >
 Słupkowy
 </Button>
 </div>
 </div>
 </CardHeader>
 <CardContent>
 <TeamHistoryChart trend={trendAll.trend} type={chartType} />
 <div className="mt-3 grid grid-cols-2 lg:grid-cols-5 gap-2 text-[11px] text-muted-foreground">
 <div>• Zapytania — lewa oś</div>
 <div>• Wakaty — lewa oś</div>
 <div>• Placements — lewa oś</div>
 <div>• Hit Ratio % — prawa oś</div>
 <div>• Fill Rate % — prawa oś</div>
 </div>
 </CardContent>
 </Card>
 )}

 {/* Ranking Delivery Leadów */}
 <Card>
 <CardHeader>
 <CardTitle>Ranking Delivery Leadów</CardTitle>
 <CardDescription>
 Kliknij nagłówek kolumny aby posortować. Korona oznacza osiągnięcie
 progu {targetPct}% hit ratio.
 </CardDescription>
 </CardHeader>
 <CardContent>
 <DlRanking
 rows={teamReport?.per_dl ?? []}
 highlightUserId={user?.id}
 targetPct={targetPct}
 />
 </CardContent>
 </Card>

 {/* Teal gradient DL → Clients */}
 <div className="rounded-lg overflow-hidden border border-border shadow-sm">
 <div className="bg-gradient-to-r from-teal-500 via-cyan-600 to-teal-600 px-4 py-3 text-white flex items-center gap-2">
 <Crown className="h-5 w-5" />
 <div>
 <div className="font-semibold text-lg">
 Delivery Lead · Przypisani Klienci
 </div>
 <div className="text-xs text-white/70">
 ⭐ = Head (główny opiekun klienta)
 </div>
 </div>
 </div>
 <div className="bg-card">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-4 py-2 w-48">
 Delivery Lead
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-4 py-2">
 Klienci
 </th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {(dlClients ?? []).map((row) => {
 const initials = row.delivery_lead.name
 .split("")
 .map((p) => p[0])
 .join("")
 .slice(0, 2)
 .toUpperCase()
 return (
 <tr key={row.delivery_lead.id}>
 <td className="px-4 py-3 align-top">
 <span className="inline-flex items-center gap-2">
 <span className="inline-flex items-center justify-center h-7 w-7 rounded-full bg-teal-100 text-teal-800 text-xs font-bold">
 {initials}
 </span>
 <span className="font-medium text-foreground">
 {row.delivery_lead.name}
 </span>
 </span>
 </td>
 <td className="px-4 py-3">
 {row.clients.length === 0 && (
 <span className="text-xs text-muted-foreground">
 —
 </span>
 )}
 <div className="flex flex-wrap gap-1.5">
 {row.clients.map((c) => (
 <span
 key={c.id}
 className={cn("inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium",
 c.is_head
 ?"bg-amber-100 text-amber-900 ring-1 ring-amber-300"
 :"bg-amber-50 text-amber-800",
 )}
 >
 {c.is_head &&"⭐"}
 {c.name}
 </span>
 ))}
 </div>
 </td>
 </tr>
 )
 })}
 </tbody>
 </table>
 {(dlClients ?? []).length === 0 && (
 <p className="text-center text-sm text-muted-foreground py-6">
 Brak przypisań DL → klient. Dodaj w /admin/team-structure.
 </p>
 )}
 </div>
 </div>
 </div>
 )
}
