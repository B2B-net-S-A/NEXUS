"use client"

import { useQuery } from"@tanstack/react-query"
import { CheckCircle2, Filter, Linkedin, RefreshCw, Send, Target, Users } from"lucide-react"

import api from"@/lib/api"
import { cn } from"@/lib/utils"
import { Badge } from"@/components/ui/badge"
import { Button } from"@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card"
import { HeroLigaMistrzow, type HeroPodiumEntry } from"@/components/v2/gamification/HeroLigaMistrzow"
import { PowerCallingSection } from"@/components/v2/gamification/PowerCallingSection"
import { RaceCard } from"@/components/v2/gamification/RaceCard"
import { ROLE_LABELS, useAuthStore } from"@/store/auth"

// ── Types ────────────────────────────────────────────────────────────────

interface RecruiterRow {
 user_id: number
 user_name: string
 role?: string | null
 primary_category?: { id: number; slug: string; name_pl: string } | null
 weryfikacje: number
 rekomendacje: number
 interviews: number
 placements: number
 hit_ratio: number
}

interface RecruitmentReport {
 period: string
 funnel: {
 weryfikacje_count: number
 rekomendacje_count: number
 interviews_count: number
 placements_count: number
 }
 funnel_efficiency: {
 weryfikacje_to_rekomendacje: number
 rekomendacje_to_interviews: number
 interviews_to_placements: number
 }
 per_recruiter: RecruiterRow[]
 top3_liga_mistrzow: RecruiterRow[]
}

interface PowerCallingResponse {
 week_label: string
 iso_week: number
 iso_year: number
 target_per_day: number
 workdays: number
 requirement_text: string
 entries: Array<{
 user_id: number
 name: string
 role: string
 primary_category: { id: number; slug: string; name_pl: string } | null
 verifications_week: number
 per_day: number
 workdays: number
 meets_target: boolean
 progress_pct: number
 }>
 meets_target_count: number
 total_count: number
}

interface CompetitionResponse {
 type: string
 period: string
 top3: HeroPodiumEntry[]
 full_ranking: HeroPodiumEntry[]
 days_remaining: number | null
 prize_pool_pln: number | null
 requirement: string | null
 points_formula: { placement: number; interview: number; recommendation: number } | null
 quarterly_prizes_pln: Record<string, number> | null
}

interface MonthlyRacesResponse {
 recommendations: RaceSection
 placements: RaceSection
}

interface RaceSection {
 period: string
 days_remaining: number
 prize: { amount_pln: number; name: string }
 requirements: string[]
 ranking: Array<{
 rank: number
 user_id: number
 name: string
 metric_value: number
 role?: string
 excluded: boolean
 }>
}

interface LinkedInMySummary {
 period: string
 me: {
 cv_added: number
 messages_sent: number
 responses_received: number
 response_rate: number
 cv_response_rate: number
 days_reported: number
 } | null
}

// ── Pastel KPI card ─────────────────────────────────────────────────────

const KPI_COLORS = {
 blue: {
 bg: "bg-sky-50 border-sky-200",
 icon: "bg-sky-100 text-sky-700",
 title: "text-sky-900",
 value: "text-sky-950",
 },
 purple: {
 bg: "bg-purple-50 border-purple-200",
 icon: "bg-purple-100 text-purple-700",
 title: "text-purple-900",
 value: "text-purple-950",
 },
 amber: {
 bg: "bg-amber-50 border-amber-200",
 icon: "bg-amber-100 text-amber-700",
 title: "text-amber-900",
 value: "text-amber-950",
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

// ── Funnel efficiency bar ────────────────────────────────────────────────

function FunnelBar({
 fromLabel,
 toLabel,
 pct,
 color,
}: {
 fromLabel: string
 toLabel: string
 pct: number
 color: keyof typeof KPI_COLORS
}) {
 const c = KPI_COLORS[color]
 return (
 <div className={cn("rounded-md border-l-4 bg-card/50 px-3 py-2", `border-${color}-400`)}>
 <div className={cn("text-[10px] uppercase tracking-wide", c.title)}>
 {fromLabel} → {toLabel}
 </div>
 <div className={cn("font-semibold text-xl font-extrabold mt-0.5", c.value)}>
 {pct.toFixed(1)}%
 </div>
 </div>
 )
}

// ── Page ────────────────────────────────────────────────────────────────

export default function RecruiterDashboard() {
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)

 const recruiterRoles = ["sourcer","tac","recruiter"] as const
 const isMeRecruiter = !!user && (recruiterRoles as readonly string[]).includes(user.role)
 const isAllowed =
 !!user && (isMeRecruiter || user.role === "admin" || user.role === "head_of_recruitment")

 const { data: report, refetch: refetchReport } = useQuery<RecruitmentReport>({
 queryKey: ["report-recruitment","month"],
 queryFn: () =>
 api.get("/api/reports/recruitment?period=month").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const myStats = report?.per_recruiter.find((r) => r.user_id === user?.id)

 const { data: quarterChampions, refetch: refetchQ } = useQuery<CompetitionResponse>({
 queryKey: ["competitions-current","quarterly_champions_recruiter"],
 queryFn: () =>
 api
 .get("/api/competitions/current?type=quarterly_champions_recruiter")
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const { data: races, refetch: refetchRaces } = useQuery<MonthlyRacesResponse>({
 queryKey: ["monthly-races","current"],
 queryFn: () =>
 api.get("/api/competitions/monthly-races").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const { data: hallOfFame } = useQuery<CompetitionResponse>({
 queryKey: ["competitions-current","hall_of_fame"],
 queryFn: () =>
 api.get("/api/competitions/current?type=hall_of_fame").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 30 * 60 * 1000,
 })

 const { data: linkedinMy } = useQuery<LinkedInMySummary>({
 queryKey: ["linkedin-my-summary","month"],
 queryFn: () =>
 api
 .get("/api/linkedin-metrics/my-summary?period=month")
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 60 * 1000,
 })

 const { data: powerCalling } = useQuery<PowerCallingResponse>({
 queryKey: ["power-calling","prev-week"],
 queryFn: () =>
 api.get("/api/reports/power-calling?offset_weeks=1").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 if (!hydrated) {
 return <div className="p-6 text-muted-foreground">Ładowanie…</div>
 }

 if (!user || !isAllowed) {
 return (
 <div className="p-6">
 <Card>
 <CardHeader>
 <CardTitle>Brak dostępu</CardTitle>
 <CardDescription>
 Panel dla ról: sourcer, TAC, rekruter. Twoja rola:{""}
 {user ? ROLE_LABELS[user.role] : "—"}.
 </CardDescription>
 </CardHeader>
 </Card>
 </div>
 )
 }

 const funnel = report?.funnel
 const eff = report?.funnel_efficiency
 const overallPct =
 funnel && funnel.weryfikacje_count
 ? (funnel.placements_count / funnel.weryfikacje_count) * 100
 : 0

 return (
 <div className="max-w-[1400px] mx-auto space-y-5 p-4 md:p-6">
 {/* Hero header with period filter */}
 <div className="flex items-start justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Panel Rekrutacja · {ROLE_LABELS[user.role]}
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground mt-1">
 {isMeRecruiter ? `Cześć, ${user.name.split("")[0]}` :"Rekrutacja — widok zespołu"}
 </h1>
 </div>
 <Button
 variant="outline"
 size="sm"
 onClick={() => {
 refetchReport()
 refetchQ()
 refetchRaces()
 }}
 >
 <RefreshCw className="h-4 w-4" />
 Odśwież
 </Button>
 </div>

 {/* KPI row — pastel cards */}
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
 <PastelKpi
 title="Weryfikacje"
 value={funnel?.weryfikacje_count ?? 0}
 subtitle={isMeRecruiter ? `Ja: ${myStats?.weryfikacje ?? 0}` :"zespół tego miesiąca"}
 icon={Filter}
 color="blue"
 />
 <PastelKpi
 title="Rekomendacje"
 value={funnel?.rekomendacje_count ?? 0}
 subtitle={isMeRecruiter ? `Ja: ${myStats?.rekomendacje ?? 0}` :"zespół tego miesiąca"}
 icon={Users}
 color="purple"
 />
 <PastelKpi
 title="Interviews"
 value={funnel?.interviews_count ?? 0}
 subtitle={isMeRecruiter ? `Ja: ${myStats?.interviews ?? 0}` :"zespół tego miesiąca"}
 icon={CheckCircle2}
 color="amber"
 />
 <PastelKpi
 title="Placements"
 value={funnel?.placements_count ?? 0}
 subtitle={isMeRecruiter ? `Ja: ${myStats?.placements ?? 0}` :"zespół tego miesiąca"}
 icon={Target}
 color="emerald"
 />
 </div>

 {/* Efektywność lejka — 4 pasy */}
 <div>
 <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
 Efektywność lejka
 </p>
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
 <FunnelBar
 fromLabel="Weryfikacje"
 toLabel="Rekomendacje"
 pct={eff?.weryfikacje_to_rekomendacje ?? 0}
 color="blue"
 />
 <FunnelBar
 fromLabel="Rekomendacje"
 toLabel="Interviews"
 pct={eff?.rekomendacje_to_interviews ?? 0}
 color="purple"
 />
 <FunnelBar
 fromLabel="Interviews"
 toLabel="Placements"
 pct={eff?.interviews_to_placements ?? 0}
 color="amber"
 />
 <FunnelBar
 fromLabel="Overall (Wer"
 toLabel="Plac)"
 pct={overallPct}
 color="emerald"
 />
 </div>
 </div>

 {/* Hero Liga Mistrzów */}
 {quarterChampions && (
 <HeroLigaMistrzow
 title="Liga Mistrzów"
 period={quarterChampions.period}
 daysRemaining={quarterChampions.days_remaining ?? 0}
 top3={quarterChampions.top3}
 fullRanking={quarterChampions.full_ranking}
 quarterlyPrizes={
 quarterChampions.quarterly_prizes_pln
 ? Object.fromEntries(
 Object.entries(quarterChampions.quarterly_prizes_pln).map(
 ([k, v]) => [Number(k), v],
 ),
 )
 : { 1: 5000, 2: 3000, 3: 2000 }
 }
 metricLabel="pkt"
 metricUnit="pkt"
 pointsFormula={quarterChampions.points_formula}
 requirement={quarterChampions.requirement}
 highlightUserId={isMeRecruiter ? user.id : null}
 />
 )}

 {/* 2 wyścigi miesięczne side-by-side */}
 {races && (
 <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
 <RaceCard
 title="Wyścig Rekomendacji"
 period={races.recommendations.period}
 daysRemaining={races.recommendations.days_remaining}
 variant="blue"
 prize={races.recommendations.prize}
 requirements={races.recommendations.requirements}
 ranking={races.recommendations.ranking}
 metricSuffix="rek."
 highlightUserId={isMeRecruiter ? user.id : null}
 />
 <RaceCard
 title="Wyścig Placementów"
 period={races.placements.period}
 daysRemaining={races.placements.days_remaining}
 variant="green"
 prize={races.placements.prize}
 requirements={races.placements.requirements}
 ranking={races.placements.ranking}
 metricSuffix="plac."
 highlightUserId={isMeRecruiter ? user.id : null}
 />
 </div>
 )}

 {/* Power Calling — pomarańczowy gradient, weryfikacje/dzień w ubiegłym tygodniu */}
 {powerCalling && (
 <PowerCallingSection
 weekLabel={powerCalling.week_label}
 requirementText={powerCalling.requirement_text}
 entries={powerCalling.entries}
 targetPerDay={powerCalling.target_per_day}
 meetsTargetCount={powerCalling.meets_target_count}
 totalCount={powerCalling.total_count}
 highlightUserId={isMeRecruiter ? user?.id : null}
 />
 )}

 {/* Hall of Fame (mały) */}
 {hallOfFame?.top3 && hallOfFame.top3.length > 0 && (
 <Card>
 <CardHeader>
 <CardTitle className="flex items-center gap-2 text-base">
 <span className="text-amber-500">🏆</span>
 Hall of Fame — all time
 </CardTitle>
 </CardHeader>
 <CardContent>
 <div className="grid grid-cols-5 gap-3 text-sm">
 {hallOfFame.top3.slice(0, 5).map((h, idx) => (
 <div
 key={h.user_id}
 className={cn("rounded-md px-3 py-2 bg-primary/10",
 h.user_id === user.id &&"ring-2 ring-primary",
 )}
 >
 <div className="text-[10px] text-muted-foreground uppercase">
 #{idx + 1}
 </div>
 <div className="font-semibold truncate">{h.name}</div>
 <div className="font-semibold text-lg font-bold text-foreground">
 {h.metric_value}
 </div>
 <div className="text-[10px] text-muted-foreground">
 placementów
 </div>
 </div>
 ))}
 </div>
 </CardContent>
 </Card>
 )}

 {/* LinkedIn metrics (manual) — tylko dla recruitera */}
 {isMeRecruiter && (
 <div>
 <div className="flex items-center gap-2 mb-2">
 <Linkedin className="h-4 w-4 text-primary" />
 <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
 Moje LinkedIn (ten miesiąc)
 </p>
 </div>
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
 <PastelKpi
 title="CV dodane"
 value={linkedinMy?.me?.cv_added ?? 0}
 subtitle={`${linkedinMy?.me?.days_reported ?? 0} dni raportu`}
 icon={Linkedin}
 color="blue"
 />
 <PastelKpi
 title="Wiadomości wysłane"
 value={linkedinMy?.me?.messages_sent ?? 0}
 icon={Send}
 color="purple"
 />
 <PastelKpi
 title="Odpowiedzi"
 value={linkedinMy?.me?.responses_received ?? 0}
 subtitle={`${linkedinMy?.me?.response_rate ?? 0}% response rate`}
 icon={CheckCircle2}
 color="amber"
 />
 <PastelKpi
 title="Quality ratio"
 value={`${linkedinMy?.me?.cv_response_rate ?? 0}%`}
 subtitle="odpowiedzi / CV dodane"
 icon={Target}
 color="emerald"
 />
 </div>
 {(!linkedinMy?.me || !linkedinMy.me.days_reported) && (
 <p className="text-xs text-muted-foreground mt-2">
 Brak raportowanych metryk LinkedIn. Admin wpisuje je w{""}
 <code className="font-mono bg-primary/10 px-1 py-0.5 rounded">
 /admin/linkedin-metrics
 </code>
 .
 </p>
 )}
 </div>
 )}

 {/* Team leaderboard */}
 <Card>
 <CardHeader>
 <CardTitle>Zespół (bieżący miesiąc)</CardTitle>
 <CardDescription>Ranking po placementach</CardDescription>
 </CardHeader>
 <CardContent>
 <div className="overflow-x-auto">
 <table className="w-full text-sm">
 <thead className="border-b border-border">
 <tr>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2 w-12">
 #
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Osoba
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Rola
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Kategoria
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Wer
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Rek
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Int
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Plac
 </th>
 <th className="text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground px-3 py-2">
 Hit %
 </th>
 </tr>
 </thead>
 <tbody className="divide-y divide-border">
 {(report?.per_recruiter ?? []).map((r, idx) => {
 const isMe = r.user_id === user.id
 return (
 <tr
 key={r.user_id}
 className={cn("hover:bg-primary/10",
 isMe &&"bg-primary/10 font-semibold",
 )}
 >
 <td className="px-3 py-2 text-muted-foreground">
 {idx + 1}
 </td>
 <td className="px-3 py-2">
 {r.user_name}
 {isMe && (
 <Badge variant="soft" size="sm" className="ml-2">
 Ja
 </Badge>
 )}
 </td>
 <td className="px-3 py-2">
 {r.role ? (
 <span
 className={cn("inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide",
 r.role === "sourcer"
 ?"bg-sky-100 text-sky-900"
 : r.role === "tac"
 ?"bg-teal-100 text-teal-900"
 : r.role === "recruiter"
 ?"bg-purple-100 text-purple-900"
 :"bg-slate-100 text-slate-900",
 )}
 >
 {r.role}
 </span>
 ) : (
 <span className="text-xs text-muted-foreground">
 —
 </span>
 )}
 </td>
 <td className="px-3 py-2">
 {r.primary_category ? (
 <span className="text-xs text-foreground">
 {r.primary_category.name_pl}
 </span>
 ) : (
 <span className="text-xs text-muted-foreground">
 —
 </span>
 )}
 </td>
 <td className="px-3 py-2 tabular-nums">{r.weryfikacje}</td>
 <td className="px-3 py-2 tabular-nums">{r.rekomendacje}</td>
 <td className="px-3 py-2 tabular-nums">{r.interviews}</td>
 <td className="px-3 py-2 tabular-nums font-semibold">
 {r.placements}
 </td>
 <td className="px-3 py-2 tabular-nums">
 {r.hit_ratio.toFixed(1)}%
 </td>
 </tr>
 )
 })}
 </tbody>
 </table>
 {(!report?.per_recruiter || report.per_recruiter.length === 0) && (
 <p className="text-center text-sm text-muted-foreground py-6">
 Brak danych w tym miesiącu.
 </p>
 )}
 </div>
 </CardContent>
 </Card>
 </div>
 )
}
