"use client";

import { useQuery } from"@tanstack/react-query";
import Link from"next/link";
import {
 AlertTriangle,
 ArrowRight,
 Briefcase,
 Building2,
 Calendar,
 FileText,
 Mic,
 Phone,
 Star,
 Target,
 TrendingUp,
 Trophy,
 UserCheck,
 Users,
 Video,
} from"lucide-react";
import api, { contractorsApi, postingsApi } from"@/lib/api";
import { cn, formatRelativeTime } from"@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from"@/components/ui/card";
import { Badge } from"@/components/ui/badge";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Separator } from"@/components/ui/separator";
import { Button } from"@/components/ui/button";
import { MyJobsWidget } from"@/components/v2/pages/dashboard/MyJobsWidget";
import { MojeKpiPanel } from "@/components/v2/kpi/MojeKpiPanel";
import { TeamKpiPanel } from "@/components/v2/kpi/TeamKpiPanel";
import { WidgetErrorBlock } from"@/components/v2/dashboard/WidgetState";
import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary";
import {
 hasAnalyticsCapability,
 useAuthStore,
} from"@/store/auth";
import { UserCog } from"lucide-react";
import {
 recruitmentFunnelStages,
} from"@/components/v2/pages/dashboard/dashboard-stats";
import {
 analyticsApi,
 type RecentHireData,
 type TeamKpiRow,
} from"@/lib/analytics";

/**
 * DashboardV2 — Dynaminds redesign. Uses the same TanStack queries as v1
 * (/api/dashboard/stats, /api/dashboard/kpis, /api/activities/feed, etc.)
 * but renders with v2 primitives + plum/burgundy/cream palette.
 */

const EVENT_ICON: Record<string, React.ReactNode> = {
 interview: <Video className="h-3.5 w-3.5" />,
 screening: <Mic className="h-3.5 w-3.5" />,
 call: <Phone className="h-3.5 w-3.5" />,
 meeting: <Calendar className="h-3.5 w-3.5" />,
 deadline: <AlertTriangle className="h-3.5 w-3.5" />,
};

const EVENT_LABEL: Record<string, string> = {
 interview: "Rozmowa",
 screening: "Screening",
 call: "Call",
 meeting: "Spotkanie",
 deadline: "Deadline",
};

// ── StatCard ───────────────────────────────────────────────────────────
interface StatProps {
 title: string;
 value: React.ReactNode;
 subtitle?: string;
 icon: React.ComponentType<{ className?: string }>;
 href?: string;
}

function StatCardV2({ title, value, subtitle, icon: Icon, href }: StatProps) {
 const inner = (
 <Card variant="default" size="md" className={href ?"hover:shadow-sm transition-all": undefined}>
 <div className="flex items-start justify-between gap-2 mb-3">
 <div className="min-w-0">
 <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 {title}
 </p>
 </div>
 <div className="flex items-center gap-2">
 <span className="inline-flex items-center justify-center h-8 w-8 rounded-md bg-primary/10 text-primary">
 <Icon className="h-4 w-4" />
 </span>
 </div>
 </div>
 <div className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground leading-none">
 {value}
 </div>
 <div className="mt-2">
 {subtitle && (
 <p className="text-xs text-muted-foreground truncate">{subtitle}</p>
 )}
 </div>
 </Card>
 );
 return href ? <Link href={href}>{inner}</Link> : inner;
}

// ── Funnel ─────────────────────────────────────────────────────────────
function FunnelV2({ data }: { data?: unknown }) {
 const stages = recruitmentFunnelStages(data);
 const allZero = stages.every((s) => s.count === 0);
 if (allZero) {
 return (
 <p className="text-sm text-muted-foreground py-4">
 Brak danych — żaden kandydat nie wszedł do lejka w wybranym okresie.
 </p>
 );
 }
 const max = Math.max(...stages.map((s) => s.count), 1);
 return (
 <div className="space-y-2.5">
 {stages.map((stage, i) => {
 const pct = Math.round((stage.count / max) * 100);
 const conv =
 i === 0 ? 100 : Math.round((stage.count / (stages[i - 1].count || 1)) * 100);
 return (
 <div key={stage.key} className="flex items-center gap-3">
 <span className="w-20 text-xs font-medium text-foreground text-right shrink-0">
 {stage.label}
 </span>
 <div className="flex-1 h-5 rounded-full bg-[hsl(var(--border))]/60 overflow-hidden">
 <div
 className="h-full rounded-full bg-gradient-to-r from-[hsl(var(--primary))] to-[hsl(var(--card))] transition-all duration-500"
 style={{ width: `${pct}%` }}
 />
 </div>
 <span className="w-8 text-xs font-bold text-foreground text-right shrink-0">
 {stage.count}
 </span>
 <span className="w-10 text-[10px] text-muted-foreground text-right shrink-0">
 {conv}%
 </span>
 </div>
 );
 })}
 </div>
 );
}

// ── Performers leaderboard ─────────────────────────────────────────────
function PerformersV2({ rows }: { rows?: TeamKpiRow[] }) {
 const lb = [...(rows ?? [])]
 .sort(
 (left, right) =>
 right.placements - left.placements ||
 right.verifications - left.verifications ||
 left.user_id - right.user_id,
 )
 .slice(0, 5);
 if (!lb.length) {
 return (
 <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
 <Trophy className="h-8 w-8 mb-2 opacity-40" />
 <p className="text-sm">Brak placementów w bieżącym miesiącu</p>
 </div>
 );
 }
 const max = Math.max(...lb.map((row) => row.placements), 1);
 return (
 <div className="space-y-3">
 {lb.map((rec, i) => {
 const initials = (rec.user_name ??"?")
 .split(/\s+/)
 .map((p: string) => p[0])
 .join("")
 .toUpperCase()
 .slice(0, 2);
 const barW = Math.round(((rec.placements ?? 0) / max) * 100);
 const rankColor =
 i === 0
 ?"text-primary"
 : i === 1
 ?"text-muted-foreground"
 : i === 2
 ?"text-primary"
 :"text-muted-foreground";
 return (
 <div key={rec.user_id} className="flex items-center gap-3">
 <span className={cn("text-xs font-bold w-4 text-center shrink-0", rankColor)}>
 {i + 1}
 </span>
 <Avatar size="sm">
 <AvatarFallback>{initials}</AvatarFallback>
 </Avatar>
 <div className="flex-1 min-w-0">
 <p className="text-sm font-medium text-foreground truncate">
 {rec.user_name}
 </p>
 <div className="mt-1 h-1.5 rounded-full bg-[hsl(var(--border))]/60 overflow-hidden">
 <div
 className="h-full rounded-full bg-primary transition-all duration-500"
 style={{ width: `${barW}%` }}
 />
 </div>
 </div>
 <span className="text-xs font-bold text-primary shrink-0">
 {rec.placements ?? 0}
 </span>
 </div>
 );
 })}
 </div>
 );
}

// ── Recent hires ───────────────────────────────────────────────────────
function RecentHiresV2({ data }: { data?: RecentHireData[] }) {
 const hires = (data ?? []).slice(0, 5);
 if (!hires.length) {
 return (
 <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
 <UserCheck className="h-8 w-8 mb-2 opacity-40" />
 <p className="text-sm">Brak ostatnich zatrudnień</p>
 </div>
 );
 }
 return (
 <div className="divide-y divide-border">
 {hires.map((hire) => (
 <Link
 key={`${hire.candidate_id}:${hire.job_id}:${hire.hired_at}`}
 href={hire.candidate_id ? `/candidates/${hire.candidate_id}` :"#"}
 className="group flex items-center gap-3 py-2.5 hover:bg-primary/10 transition-colors rounded-md -mx-2 px-2"
 >
 <Avatar size="sm">
 <AvatarFallback>
 {(hire.candidate_name ??"?").charAt(0).toUpperCase()}
 </AvatarFallback>
 </Avatar>
 <div className="flex-1 min-w-0">
 <p className="text-sm font-medium text-foreground truncate group-hover:text-primary">
 {hire.candidate_name ??
 (hire.candidate_id ? `Kandydat #${hire.candidate_id}` : "Kandydat")}
 </p>
 <p className="text-xs text-muted-foreground truncate">
 {hire.job_title ??""}
 {hire.client_name ? ` · ${hire.client_name}` :""}
 </p>
 </div>
 <span className="text-xs text-muted-foreground shrink-0 whitespace-nowrap">
 {hire.hired_at ? formatRelativeTime(hire.hired_at) : ""}
 </span>
 </Link>
 ))}
 </div>
 );
}

// ── Upcoming events ────────────────────────────────────────────────────
function UpcomingEventsV2({ events }: { events?: any[] }) {
 if (!events?.length) {
 return (
 <p className="text-sm text-muted-foreground py-4">
 Brak nadchodzących wydarzeń.
 </p>
 );
 }
 return (
 <div className="space-y-2">
 {events.slice(0, 4).map((e: any) => {
 const when = e.start ?? e.start_at ?? e.scheduled_at ?? e.date;
 return (
 <div
 key={e.id}
 className="flex items-center gap-3 py-2 border-b border-border last:border-0"
 >
 <span className="inline-flex items-center justify-center h-7 w-7 rounded-md bg-primary/10 text-primary shrink-0">
 {EVENT_ICON[e.type] ?? <Calendar className="h-3.5 w-3.5" />}
 </span>
 <div className="flex-1 min-w-0">
 <p className="text-sm font-medium text-foreground truncate">
 {e.title ?? e.subject ?? EVENT_LABEL[e.type] ??"Wydarzenie"}
 </p>
 <p className="text-xs text-muted-foreground">
 {when ? formatRelativeTime(when) : ""}
 </p>
 </div>
 </div>
 );
 })}
 </div>
 );
}

// ── Placements ─────────────────────────────────────────────────────────
function PlacementsV2({
 placements,
 expiringContracts,
}: {
 placements?: number;
 expiringContracts?: number;
}) {
 const byClient: Record<string, number> = {};
 const hasData = Object.keys(byClient).length > 0;
 const max = hasData ? Math.max(...(Object.values(byClient) as number[])) : 1;
 return (
 <Card>
 <CardHeader>
 <div className="flex items-center gap-3">
 <span className="inline-flex items-center justify-center h-10 w-10 rounded-lg bg-primary/10 text-primary">
 <Target className="h-5 w-5" />
 </span>
 <div className="flex-1">
 <CardTitle>Placements — ten miesiąc</CardTitle>
 <CardDescription>zatrudnienia B2B.net</CardDescription>
 </div>
 <span className="font-semibold text-3xl font-extrabold text-foreground tracking-[-0.02em]">
 {placements ?? "—"}
 </span>
 </div>
 </CardHeader>
 {hasData && (
 <CardContent>
 <div className="space-y-2">
 {Object.entries(byClient).slice(0, 4).map(([client, count]) => (
 <div key={client} className="flex items-center gap-3 text-xs">
 <span className="flex-1 truncate text-foreground">{client}</span>
 <div className="w-24 rounded-full bg-[hsl(var(--border))]/60 h-1.5 overflow-hidden">
 <div
 className="h-full rounded-full bg-primary"
 style={{ width: `${Math.min(100, ((count as number) / max) * 100)}%` }}
 />
 </div>
 <span className="font-semibold text-foreground w-4 text-right">
 {count as number}
 </span>
 </div>
 ))}
 </div>
 </CardContent>
 )}
 {!!expiringContracts && (
 <CardContent>
 <div className="mt-2 flex items-center gap-2 text-xs text-[#7a4c0d] bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
 <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
 {expiringContracts} kontrakt{expiringContracts > 1 ?"y" :""} kończą się w ciągu 30 dni.
 </div>
 </CardContent>
 )}
 </Card>
 );
}

// ── Contractor drafts widget ───────────────────────────────────────────
function ContractorDraftsWidget() {
 const { user } = useAuthStore();
 const canView = hasAnalyticsCapability(user, "view_client_operations");
 const { data } = useQuery({
 queryKey: ["contractor-stats-widget"],
 queryFn: () => contractorsApi.stats().then((r) => r.data),
 enabled: canView,
 staleTime: 60 * 1000,
 });

 // Gate visibility to roles that actually fill in contracts; recruiters
 // and sourcers don't own the draft completion step.
 if (!canView) {
 return null;
 }

 const incomplete = data?.drafts_incomplete ?? 0;
 if (incomplete === 0) return null;

 return (
 <Link
 href="/contractors?tab=draft"
 className="block group"
 aria-label={`${incomplete} draftów do uzupełnienia`}
 >
 <Card className="border-amber-200 bg-amber-50 !p-4 flex items-center gap-3 transition-colors group-hover:bg-amber-100">
 <div className="h-10 w-10 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
 <UserCog className="h-5 w-5 text-amber-700" />
 </div>
 <div className="flex-1">
 <p className="text-sm font-semibold text-amber-900">
 Drafty do uzupełnienia: {incomplete}
 </p>
 <p className="text-xs text-amber-800">
 Kontraktorzy czekają na uzupełnienie stawek i dat — kliknij, żeby
 otworzyć listę.
 </p>
 </div>
 <ArrowRight className="h-4 w-4 text-amber-800" />
 </Card>
 </Link>
 );
}

// ── Main ───────────────────────────────────────────────────────────────
export function DashboardV2() {
 const user = useAuthStore((state) => state.user);
 const hydrated = useAuthStore((state) => state.hydrated);
 const canViewOverview = hasAnalyticsCapability(user, "view_operational_aggregates");
 const canViewRecruitmentTeam = hasAnalyticsCapability(user, "view_recruitment_team");
 const canViewPersonalRecruitment = hasAnalyticsCapability(
 user,
 "view_personal_recruitment_kpis",
 );
 const canViewClientOperations = hasAnalyticsCapability(user, "view_client_operations");
 const canNavigateRecruitment = canViewRecruitmentTeam || canViewPersonalRecruitment;
 const canViewDetailedOperations =
 canViewRecruitmentTeam || canViewPersonalRecruitment || canViewClientOperations;

 const {
 data: statsEnvelope,
 isLoading: statsLoading,
 isFetching: statsFetching,
 isError: statsIsError,
 error: statsError,
 refetch: refetchStats,
 } = useQuery({
 queryKey: ["analytics-v1", "overview", "month"],
 queryFn: () => analyticsApi.overview("month"),
 enabled: hydrated && canViewOverview,
 });

 const {
 data: recentHiresEnvelope,
 isLoading: recentHiresLoading,
 isFetching: recentHiresFetching,
 isError: recentHiresIsError,
 error: recentHiresError,
 refetch: refetchRecentHires,
 } = useQuery({
 queryKey: ["analytics-v1", "recruitment", "recent-hires", "month"],
 queryFn: () => analyticsApi.recentHires("month", 10),
 enabled: hydrated && canViewRecruitmentTeam,
 staleTime: 60 * 1000,
 });

 const {
 data: upcomingEvents,
 isLoading: upcomingLoading,
 isError: upcomingIsError,
 error: upcomingError,
 refetch: refetchUpcoming,
 } = useQuery({
 queryKey: ["upcoming-events"],
 queryFn: () =>
 api
 .get("/api/calendar/events", {
 params: { upcoming: true, limit: 5, start_from: new Date().toISOString() },
 })
 .then((r) => (Array.isArray(r.data) ? r.data.slice(0, 5) : [])),
 enabled: hydrated && canViewDetailedOperations,
 staleTime: 60 * 1000,
 });

 const {
 data: funnelEnvelope,
 isLoading: reportLoading,
 isFetching: reportFetching,
 isError: reportIsError,
 error: reportError,
 refetch: refetchReport,
 } = useQuery({
 queryKey: ["analytics-v1", "recruitment", "funnel", "month"],
 queryFn: () => analyticsApi.recruitmentFunnel("month"),
 enabled: hydrated && canViewRecruitmentTeam,
 staleTime: 5 * 60 * 1000,
 });

 const {
 data: teamKpisEnvelope,
 isLoading: teamKpisLoading,
 isFetching: teamKpisFetching,
 isError: teamKpisIsError,
 error: teamKpisError,
 refetch: refetchTeamKpis,
 } = useQuery({
 queryKey: ["analytics-v1", "team", "kpis", "month", "dashboard-ranking"],
 queryFn: () => analyticsApi.teamKpis("month"),
 enabled: hydrated && canViewRecruitmentTeam,
 staleTime: 5 * 60 * 1000,
 });

 const { data: postingsStats, isError: postingsIsError } = useQuery({
 queryKey: ["postings-stats"],
 queryFn: () => postingsApi.stats().then((r) => r.data),
 enabled: hydrated && canViewOverview,
 staleTime: 60 * 1000,
 });

 const { data: health, isError: healthIsError } = useQuery<{
 status?: string;
 version?: string;
 checks?: Record<string, unknown>;
 }>({
 queryKey: ["system-health"],
 queryFn: () => api.get("/api/health").then((r) => r.data),
 enabled: hydrated && canViewOverview,
 staleTime: 60 * 1000,
 });

 const recentHires = recentHiresEnvelope?.data.hires ?? [];
 const stats = statsEnvelope?.data;
 const recruitmentFunnel = funnelEnvelope?.data;
 const placements = recruitmentFunnel?.placed;

 return (
 <div className="max-w-[1400px] mx-auto space-y-6">
 {/* Hero header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Nexus · B2B.net S.A.
 </p>
 <h1 className="font-semibold text-3xl md:text-4xl font-extrabold tracking-[-0.025em] text-foreground mt-1">
 Dashboard
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 Twój pipeline rekrutacyjny w jednym widoku.
 </p>
 </div>
 {canViewDetailedOperations && <div className="flex items-center gap-2">
 <Link href="/candidates">
 <Button variant="outline" size="sm">
 Kandydaci <ArrowRight className="h-3.5 w-3.5" />
 </Button>
 </Link>
 <Link href="/jobs">
 <Button variant="primary" size="sm">
 Oferty <ArrowRight className="h-3.5 w-3.5" />
 </Button>
 </Link>
 </div>}
 </div>

 {/* Moje KPI — osobisty panel */}
 {canViewPersonalRecruitment && <MojeKpiPanel />}

 {/* KPI zespołu — managerski widok per osoba (admin/HoR/DL) */}
 {canViewRecruitmentTeam && <TeamKpiPanel className="mt-4" />}

 {/* KPI hero row */}
 <section>
 <StatsBoundary
 isLoading={statsLoading}
 isFetching={statsFetching && !statsLoading}
 isError={statsIsError}
 error={statsError}
 isEmpty={!statsEnvelope}
 quality={statsEnvelope?.quality}
 generatedAt={statsEnvelope?.generated_at}
 onRetry={() => refetchStats()}
 loadingFallback={
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
 {Array.from({ length: 4 }).map((_, i) => (
 <Card key={i} className="animate-pulse">
 <div className="h-4 bg-[hsl(var(--border))] rounded w-24 mb-3" />
 <div className="h-8 bg-[hsl(var(--border))] rounded w-20" />
 </Card>
 ))}
 </div>
 }
 >
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
 <StatCardV2
 title="Kandydaci"
 value={stats?.candidates?.total ??"—"}
 subtitle={
 typeof stats?.candidates?.active === "number"
 ? `${stats.candidates.active} aktywnych`
 : undefined
 }
 icon={Users}
 href={canNavigateRecruitment ? "/candidates" : undefined}
 />
 <StatCardV2
 title="Otwarte oferty"
 value={stats?.jobs?.open ??"—"}
 subtitle={
 typeof stats?.jobs?.total === "number"
 ? `${stats.jobs.total} łącznie`
 : undefined
 }
 icon={Briefcase}
 href={canNavigateRecruitment ? "/jobs" : undefined}
 />
 <StatCardV2
 title="Klienci"
 value={stats?.clients?.total ??"—"}
 subtitle={
 typeof stats?.clients?.active === "number"
 ? `${stats.clients.active} aktywnych`
 : undefined
 }
 icon={Building2}
 href={canViewClientOperations ? "/clients" : undefined}
 />
 <StatCardV2
 title="Aktywne kontrakty"
 value={stats?.contracts?.active ??"—"}
 subtitle={
 typeof stats?.contracts?.expiring_30_days === "number"
 ? `${stats.contracts.expiring_30_days} kończących się`
 : undefined
 }
 icon={FileText}
 href={canViewClientOperations ? "/contracts" : undefined}
 />
 </div>
 </StatsBoundary>
 </section>

 {/* Contractor drafts — only visible when count > 0 and role qualifies */}
 <ContractorDraftsWidget />

 {/* My projects (Recruiter Ownership) */}
 {canNavigateRecruitment && <MyJobsWidget />}

 {/* Pipeline + Hires */}
 {canViewRecruitmentTeam && (
 <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
 <Card className="lg:col-span-3">
 <CardHeader>
 <div className="flex items-center gap-2">
 <TrendingUp className="h-4 w-4 text-primary" />
 <CardTitle>Lejek rekrutacji</CardTitle>
 <Badge variant="soft" size="sm" className="ml-auto">
 Bieżący miesiąc
 </Badge>
 </div>
 </CardHeader>
 <CardContent>
 <StatsBoundary
 isLoading={reportLoading}
 isFetching={reportFetching && !reportLoading}
 isError={reportIsError}
 error={reportError}
 isEmpty={!funnelEnvelope}
 quality={funnelEnvelope?.quality}
 generatedAt={funnelEnvelope?.generated_at}
 onRetry={() => refetchReport()}
 >
 <FunnelV2 data={recruitmentFunnel} />
 </StatsBoundary>
 </CardContent>
 </Card>

 <Card className="lg:col-span-2">
 <CardHeader>
 <div className="flex items-center gap-2">
 <UserCheck className="h-4 w-4 text-primary" />
 <CardTitle>Ostatnie zatrudnienia</CardTitle>
 <Link
 href="/insights?tab=rekrutacja"
 className="ml-auto text-xs text-primary hover:underline"
 >
 Wszystkie →
 </Link>
 </div>
 </CardHeader>
 <CardContent>
 <StatsBoundary
 isLoading={recentHiresLoading}
 isFetching={recentHiresFetching && !recentHiresLoading}
 isError={recentHiresIsError}
 error={recentHiresError}
 isEmpty={!recentHiresEnvelope || recentHires.length === 0}
 emptyTitle="Brak zatrudnień w bieżącym miesiącu"
 quality={recentHiresEnvelope?.quality}
 generatedAt={recentHiresEnvelope?.generated_at}
 onRetry={() => refetchRecentHires()}
 >
 <RecentHiresV2 data={recentHires} />
 </StatsBoundary>
 </CardContent>
 </Card>
 </div>
 )}

 {/* Performers + Upcoming */}
 {canViewRecruitmentTeam && (
 <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
 <Card className="lg:col-span-2">
 <CardHeader>
 <div className="flex items-center gap-2">
 <Star className="h-4 w-4 text-amber-500" />
 <CardTitle>Najlepsi rekruterzy — placementy</CardTitle>
 <Link
 href="/insights?tab=rekrutacja"
 className="ml-auto text-xs text-primary hover:underline"
 >
 Analityka →
 </Link>
 </div>
 </CardHeader>
 <CardContent>
 <StatsBoundary
 isLoading={teamKpisLoading}
 isFetching={teamKpisFetching && !teamKpisLoading}
 isError={teamKpisIsError}
 error={teamKpisError}
 isEmpty={!teamKpisEnvelope || teamKpisEnvelope.data.users.length === 0}
 emptyTitle="Brak KPI zespołu w bieżącym miesiącu"
 quality={teamKpisEnvelope?.quality}
 generatedAt={teamKpisEnvelope?.generated_at}
 onRetry={() => refetchTeamKpis()}
 >
 <PerformersV2 rows={teamKpisEnvelope?.data.users} />
 </StatsBoundary>
 </CardContent>
 </Card>

 <Card>
 <CardHeader>
 <div className="flex items-center gap-2">
 <Calendar className="h-4 w-4 text-primary" />
 <CardTitle>Nadchodzące</CardTitle>
 <Link
 href="/calendar"
 className="ml-auto text-xs text-primary hover:underline"
 >
 Kalendarz →
 </Link>
 </div>
 </CardHeader>
 <CardContent>
 {upcomingLoading ? (
 <p className="text-sm text-muted-foreground py-4">Ładowanie wydarzeń…</p>
 ) : upcomingIsError ? (
 <WidgetErrorBlock
 title="Nie udało się załadować wydarzeń."
 error={upcomingError}
 onRetry={() => refetchUpcoming()}
 />
 ) : (
 <UpcomingEventsV2 events={upcomingEvents} />
 )}
 </CardContent>
 </Card>
 </div>
 )}

 {/* Placements + system */}
 <div
 className={cn(
 "grid grid-cols-1 gap-4",
 canViewRecruitmentTeam && "lg:grid-cols-3",
 )}
 >
 {canViewRecruitmentTeam && (
 <div className="lg:col-span-2">
 <PlacementsV2
 placements={placements}
 expiringContracts={stats?.contracts?.expiring_30_days}
 />
 </div>
 )}

 <Card>
 <CardHeader>
 <CardTitle>Zdrowie systemu</CardTitle>
 <CardDescription>Integracje i job boards</CardDescription>
 </CardHeader>
 <CardContent className="space-y-2 text-sm">
 <HealthRow
 label="Backend API"
 detail={
 healthIsError
 ? "Niedostępny"
 : health?.version
 ? `wersja ${health.version}`
 : health?.status ?? "Brak danych"
 }
 status={healthIsError ? "unknown" : normalizeHealthStatus(health?.status)}
 />
 <Separator />
 <HealthRow
 label="Baza danych"
 detail={healthCheckDetail(health?.checks?.database, healthIsError)}
 status={
 healthIsError
 ? "unknown"
 : normalizeHealthStatus(health?.checks?.database)
 }
 />
 <Separator />
 <HealthRow
 label="Publikacje ofert"
 detail={
 postingsIsError
 ? "Niedostępne"
 : typeof postingsStats?.total === "number"
 ? `${postingsStats.total} aktywnych`
 : "Brak danych"
 }
 status={postingsIsError ? "unknown" : "info"}
 />
 </CardContent>
 </Card>
 </div>
 </div>
 );
}

function HealthRow({
 label,
 detail,
 status,
}: {
 label: string;
 detail: string;
 status: "healthy" | "unhealthy" | "unknown" | "info";
}) {
 return (
 <div className="flex items-center justify-between py-1">
 <span className="text-foreground">{label}</span>
 <span className="inline-flex items-center gap-1.5 text-xs">
 <span
 className={cn("h-2 w-2 rounded-full",
 status === "healthy"
 ? "bg-primary"
 : status === "unhealthy"
 ? "bg-destructive"
 : status === "info"
 ? "bg-primary/60"
 : "bg-muted-foreground"
 )}
 />
 <span className="text-muted-foreground">{detail}</span>
 </span>
 </div>
 );
}

function normalizeHealthStatus(value: unknown): "healthy" | "unhealthy" | "unknown" {
 if (value === true) return "healthy";
 if (value === false) return "unhealthy";
 if (typeof value !== "string") return "unknown";
 const normalized = value.toLowerCase();
 if (["healthy", "ok", "active", "configured"].includes(normalized)) return "healthy";
 if (["unhealthy", "failed", "error", "misconfigured"].includes(normalized)) {
 return "unhealthy";
 }
 return "unknown";
}

function healthCheckDetail(value: unknown, requestFailed: boolean): string {
 if (requestFailed) return "Niedostępna";
 if (typeof value === "string") return value;
 if (value === true) return "healthy";
 if (value === false) return "unhealthy";
 return "Brak danych";
}
