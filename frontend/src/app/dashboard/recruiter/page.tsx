"use client"

import { useQuery } from"@tanstack/react-query"
import { CheckCircle2, Filter, Linkedin, RefreshCw, Send, Target, Users } from"lucide-react"

import api from"@/lib/api"
import { cn } from"@/lib/utils"
import { Badge } from"@/components/ui/badge"
import { Button } from"@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card"
import { StatCard, StatCardGrid, DataTable, type DataTableColumn } from"@/components/ds"
import { HeroLigaMistrzow, type HeroPodiumEntry } from"@/components/v2/gamification/HeroLigaMistrzow"
import { PowerCallingSection } from"@/components/v2/gamification/PowerCallingSection"
import CallStatsWidget from"@/components/dashboard/CallStatsWidget"
import { RaceCard } from"@/components/v2/gamification/RaceCard"
import { WidgetErrorBlock } from"@/components/v2/dashboard/WidgetState"
import { MojeKpiPanel } from "@/components/v2/kpi/MojeKpiPanel"
import { ROLE_LABELS, hasRole, useAuthStore } from"@/store/auth"

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
 verification_target_per_day: number
 workdays: number
 requirement_text: string
 calls_available: boolean
 entries: Array<{
 user_id: number
 name: string
 role: string
 primary_category: { id: number; slug: string; name_pl: string } | null
 calls_week: number | null
 calls_per_day: number | null
 verifications_week: number
 verifications_per_day: number
 workdays: number
 meets_call_target: boolean | null
 meets_verification_target: boolean
 progress_pct: number | null
 }>
 meets_target_count: number | null
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

// ── Funnel efficiency tile (token-based) ─────────────────────────────────

function FunnelTile({
 fromLabel,
 toLabel,
 pct,
}: {
 fromLabel: string
 toLabel: string
 pct: number
}) {
 return (
 <div className="rounded-md border-l-2 border-primary bg-card px-3 py-2">
 <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
 {fromLabel} → {toLabel}
 </div>
 <div className="font-semibold text-xl mt-0.5 tabular-nums text-foreground">
 {pct.toFixed(1)}%
 </div>
 </div>
 )
}

// ── Page ────────────────────────────────────────────────────────────────

export default function RecruiterDashboard() {
 const user = useAuthStore((s) => s.user)
 const hydrated = useAuthStore((s) => s.hydrated)

 const isMeRecruiter = hasRole(user, "sourcer", "tac", "recruiter")
 const isAllowed = hasRole(
 user,
 "sourcer",
 "tac",
 "recruiter",
 "admin",
 "head_of_recruitment",
 )

 const {
 data: report,
 isError: reportIsError,
 error: reportError,
 refetch: refetchReport,
 } = useQuery<RecruitmentReport>({
 queryKey: ["report-recruitment","month"],
 queryFn: () =>
 api.get("/api/reports/recruitment?period=month").then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const myStats = report?.per_recruiter.find((r) => r.user_id === user?.id)

 const {
 data: quarterChampions,
 isError: qIsError,
 error: qError,
 refetch: refetchQ,
 } = useQuery<CompetitionResponse>({
 queryKey: ["competitions-current","quarterly_champions_recruiter"],
 queryFn: () =>
 api
 .get("/api/competitions/current?type=quarterly_champions_recruiter")
 .then((r) => r.data),
 enabled: hydrated && isAllowed,
 staleTime: 5 * 60 * 1000,
 })

 const {
 data: races,
 isError: racesIsError,
 error: racesError,
 refetch: refetchRaces,
 } = useQuery<MonthlyRacesResponse>({
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

 const teamRows = report?.per_recruiter ?? []
 const teamColumns: Array<DataTableColumn<RecruiterRow>> = [
 {
 key: "rank",
 header: "#",
 width: "3rem",
 render: (r) => (
 <span className="text-muted-foreground tabular-nums">
 {teamRows.indexOf(r) + 1}
 </span>
 ),
 },
 {
 key: "person",
 header: "Osoba",
 render: (r) => (
 <span className={cn(r.user_id === user.id && "font-semibold")}>
 {r.user_name}
 {r.user_id === user.id && (
 <Badge variant="soft" size="sm" className="ml-2">
 Ja
 </Badge>
 )}
 </span>
 ),
 },
 {
 key: "role",
 header: "Rola",
 render: (r) =>
 r.role ? (
 <Badge variant="soft" size="sm" uppercase>
 {r.role}
 </Badge>
 ) : (
 <span className="text-muted-foreground">—</span>
 ),
 },
 {
 key: "category",
 header: "Kategoria",
 render: (r) =>
 r.primary_category ? (
 <span className="text-foreground">{r.primary_category.name_pl}</span>
 ) : (
 <span className="text-muted-foreground">—</span>
 ),
 },
 {
 key: "weryfikacje",
 header: "Wer",
 render: (r) => <span className="tabular-nums">{r.weryfikacje}</span>,
 },
 {
 key: "rekomendacje",
 header: "Rek",
 render: (r) => <span className="tabular-nums">{r.rekomendacje}</span>,
 },
 {
 key: "interviews",
 header: "Int",
 render: (r) => <span className="tabular-nums">{r.interviews}</span>,
 },
 {
 key: "placements",
 header: "Plac",
 render: (r) => (
 <span className="tabular-nums font-semibold">{r.placements}</span>
 ),
 },
 {
 key: "hit_ratio",
 header: "Hit %",
 render: (r) => (
 <span className="tabular-nums">{r.hit_ratio.toFixed(1)}%</span>
 ),
 },
 ]

 return (
 <div className="max-w-[1400px] mx-auto space-y-5 p-4 md:p-6">
 {/* Hero header with period filter */}
 <div className="flex items-start justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Panel Rekrutacja · {ROLE_LABELS[user.role]}
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground mt-1">
 {isMeRecruiter
 ? `Cześć, ${user.name.trim().split(/\s+/)[0] || "tam"}`
 : "Rekrutacja — widok zespołu"}
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

 {/* Moje KPI — osobisty panel (verifier-anchored, niezależny od raportu zespołu) */}
 <MojeKpiPanel className="mb-1" />

 {/* Report-driven sections (KPI + lejka). Without explicit error handling
 these would silently render zeros when the report endpoint errors — making
 the dashboard look broken instead of failed. */}
 {reportIsError ? (
 <Card>
 <WidgetErrorBlock
 title="Nie udało się załadować raportu rekrutacji."
 error={reportError}
 onRetry={() => refetchReport()}
 />
 </Card>
 ) : (
 <>
 {/* KPI row — DS StatCards */}
 <StatCardGrid>
 <StatCard
 label="Weryfikacje"
 value={funnel?.weryfikacje_count ?? 0}
 sub={isMeRecruiter ? `Ja: ${myStats?.weryfikacje ?? 0}` :"zespół tego miesiąca"}
 icon={Filter}
 />
 <StatCard
 label="Rekomendacje"
 value={funnel?.rekomendacje_count ?? 0}
 sub={isMeRecruiter ? `Ja: ${myStats?.rekomendacje ?? 0}` :"zespół tego miesiąca"}
 icon={Users}
 />
 <StatCard
 label="Interviews"
 value={funnel?.interviews_count ?? 0}
 sub={isMeRecruiter ? `Ja: ${myStats?.interviews ?? 0}` :"zespół tego miesiąca"}
 icon={CheckCircle2}
 />
 <StatCard
 label="Placements"
 value={funnel?.placements_count ?? 0}
 sub={isMeRecruiter ? `Ja: ${myStats?.placements ?? 0}` :"zespół tego miesiąca"}
 icon={Target}
 />
 </StatCardGrid>

 {/* Efektywność lejka — 4 pasy */}
 <div>
 <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-2">
 Efektywność lejka
 </p>
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
 <FunnelTile
 fromLabel="Weryfikacje"
 toLabel="Rekomendacje"
 pct={eff?.weryfikacje_to_rekomendacje ?? 0}
 />
 <FunnelTile
 fromLabel="Rekomendacje"
 toLabel="Interviews"
 pct={eff?.rekomendacje_to_interviews ?? 0}
 />
 <FunnelTile
 fromLabel="Interviews"
 toLabel="Placements"
 pct={eff?.interviews_to_placements ?? 0}
 />
 <FunnelTile
 fromLabel="Overall (Wer"
 toLabel="Plac)"
 pct={overallPct}
 />
 </div>
 </div>
 </>
 )}

 {/* Hero Liga Mistrzów */}
 {qIsError ? (
 <Card>
 <WidgetErrorBlock
 title="Nie udało się załadować Ligi Mistrzów."
 error={qError}
 onRetry={() => refetchQ()}
 />
 </Card>
 ) : quarterChampions ? (
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
 ) : null}

 {/* 2 wyścigi miesięczne side-by-side */}
 {racesIsError ? (
 <Card>
 <WidgetErrorBlock
 title="Nie udało się załadować wyścigów miesięcznych."
 error={racesError}
 onRetry={() => refetchRaces()}
 />
 </Card>
 ) : races ? (
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
 ) : null}

 {/* Power Calling — completed CloudTalk calls + separate verification target. */}
 {powerCalling && (
 <PowerCallingSection
 weekLabel={powerCalling.week_label}
 requirementText={powerCalling.requirement_text}
 callsAvailable={powerCalling.calls_available}
 entries={powerCalling.entries}
 targetPerDay={powerCalling.target_per_day}
 verificationTargetPerDay={powerCalling.verification_target_per_day}
 meetsTargetCount={powerCalling.meets_target_count}
 totalCount={powerCalling.total_count}
 highlightUserId={isMeRecruiter ? user?.id : null}
 />
 )}

 {/* CloudTalk stats — auto-hides when integration disabled and 0 historical calls */}
 <CallStatsWidget />

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
 <StatCardGrid>
 <StatCard
 label="CV dodane"
 value={linkedinMy?.me?.cv_added ?? 0}
 sub={`${linkedinMy?.me?.days_reported ?? 0} dni raportu`}
 icon={Linkedin}
 />
 <StatCard
 label="Wiadomości wysłane"
 value={linkedinMy?.me?.messages_sent ?? 0}
 icon={Send}
 />
 <StatCard
 label="Odpowiedzi"
 value={linkedinMy?.me?.responses_received ?? 0}
 sub={`${linkedinMy?.me?.response_rate ?? 0}% response rate`}
 icon={CheckCircle2}
 />
 <StatCard
 label="Quality ratio"
 value={`${linkedinMy?.me?.cv_response_rate ?? 0}%`}
 sub="odpowiedzi / CV dodane"
 icon={Target}
 />
 </StatCardGrid>
 {(!linkedinMy?.me || !linkedinMy.me.days_reported) && (
 <p className="text-xs text-muted-foreground mt-2">
 Brak raportowanych metryk LinkedIn. Admin wpisuje je w{""}
 <code className="font-mono bg-primary/10 px-1 py-0.5 rounded">
 /settings/linkedin-metrics
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
 {reportIsError ? (
 <WidgetErrorBlock
 title="Nie udało się załadować zespołu."
 error={reportError}
 onRetry={() => refetchReport()}
 />
 ) : (
 <DataTable<RecruiterRow>
 columns={teamColumns}
 rows={report?.per_recruiter ?? []}
 getRowKey={(r) => r.user_id}
 rowHighlighted={(r) => r.user_id === user?.id}
 empty={
 <p className="text-sm text-muted-foreground">
 Brak danych w tym miesiącu.
 </p>
 }
 />
 )}
 </CardContent>
 </Card>
 </div>
 )
}
