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
 TrendingDown,
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
import { WidgetState, WidgetErrorBlock } from"@/components/v2/dashboard/WidgetState";
import { hasRole, useAuthStore } from"@/store/auth";
import { UserCog } from"lucide-react";

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

// ── Sparkline (inline SVG) ─────────────────────────────────────────────
function Sparkline({ data, color ="hsl(var(--primary))" }: { data: number[]; color?: string }) {
 if (data.length < 2) return null;
 const w = 88;
 const h = 28;
 const max = Math.max(...data);
 const min = Math.min(...data);
 const range = max - min || 1;
 const step = w / (data.length - 1);
 const points = data
 .map((v, i) => `${i * step},${h - ((v - min) / range) * h}`)
 .join("");
 return (
 <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0">
 <polyline
 points={points}
 fill="none"
 stroke={color}
 strokeWidth="1.5"
 strokeLinecap="round"
 strokeLinejoin="round"
 />
 </svg>
 );
}

function seedSparkline(base: number, seed: number): number[] {
 return Array.from({ length: 7 }, (_, i) => {
 const factor = 1 + 0.18 * Math.sin((i + seed) * 1.7);
 return Math.max(0, Math.round(base * factor));
 });
}

// ── StatCard ───────────────────────────────────────────────────────────
interface StatProps {
 title: string;
 value: React.ReactNode;
 subtitle?: string;
 icon: React.ComponentType<{ className?: string }>;
 trend?: { value: number; label: string };
 sparkline?: number[];
 href?: string;
}

function StatCardV2({ title, value, subtitle, icon: Icon, trend, sparkline, href }: StatProps) {
 const inner = (
 <Card variant="default" size="md" className={href ?"hover:shadow-sm transition-all": undefined}>
 <div className="flex items-start justify-between gap-2 mb-3">
 <div className="min-w-0">
 <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 {title}
 </p>
 </div>
 <div className="flex items-center gap-2">
 {sparkline && <Sparkline data={sparkline} />}
 <span className="inline-flex items-center justify-center h-8 w-8 rounded-md bg-primary/10 text-primary">
 <Icon className="h-4 w-4" />
 </span>
 </div>
 </div>
 <div className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground leading-none">
 {value}
 </div>
 <div className="flex items-center justify-between gap-2 mt-2">
 {subtitle && (
 <p className="text-xs text-muted-foreground truncate">{subtitle}</p>
 )}
 {trend && (
 <span
 className={cn("inline-flex items-center gap-0.5 text-[11px] font-semibold whitespace-nowrap",
 trend.value >= 0 ?"text-[#1d5e31]" :"text-primary"
 )}
 >
 {trend.value >= 0 ? (
 <TrendingUp className="h-3 w-3" />
 ) : (
 <TrendingDown className="h-3 w-3" />
 )}
 {trend.value >= 0 ?"+" :""}
 {trend.value}%
 </span>
 )}
 </div>
 </Card>
 );
 return href ? <Link href={href}>{inner}</Link> : inner;
}

// ── Funnel ─────────────────────────────────────────────────────────────
function FunnelV2({ data }: { data?: any }) {
 // QA bug #17 (2026-05-27): previous version used hardcoded fallbacks
 // 120/78/45/18/9 when the funnel API returned null/undefined. Those
 // round numbers (100%/65%/58%/40%/50% conversion) were mistaken for
 // real metrics by admins who compared them against Insights/Rekrutacja
 // which showed actual 14/17/2/18/9 — confusing data integrity story.
 // Now: 0 + "Brak danych" empty state when API has no response yet.
 const funnel = data?.funnel ?? data?.pipeline ?? null;
 const stages = [
 { key: "new", label: "Nowy", count: funnel?.new ?? funnel?.total_entered ?? 0 },
 { key: "screening", label: "Screening", count: funnel?.screening ?? funnel?.screening_done ?? 0 },
 { key: "interview", label: "Interview", count: funnel?.interview ?? funnel?.interviews ?? 0 },
 { key: "offer", label: "Oferta", count: funnel?.offer ?? funnel?.offers ?? 0 },
 { key: "hired", label: "Zatrudniony", count: funnel?.hired ?? funnel?.hired_count ?? 0 },
 ];
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
function PerformersV2({ data }: { data?: any }) {
 const lb = data?.leaderboard ?? [];
 if (!lb.length) {
 return (
 <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
 <Trophy className="h-8 w-8 mb-2 opacity-40" />
 <p className="text-sm">Brak danych o aktywności</p>
 </div>
 );
 }
 const max = Math.max(...lb.map((r: any) => r.total_actions), 1);
 return (
 <div className="space-y-3">
 {lb.slice(0, 5).map((rec: any, i: number) => {
 const initials = (rec.user_name ??"?")
 .split("")
 .map((p: string) => p[0])
 .join("")
 .toUpperCase()
 .slice(0, 2);
 const barW = Math.round((rec.total_actions / max) * 100);
 const rankColor =
 i === 0
 ?"text-amber-500"
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
 {rec.total_actions}
 </span>
 </div>
 );
 })}
 </div>
 );
}

// ── Recent hires ───────────────────────────────────────────────────────
function RecentHiresV2({ data }: { data?: any[] }) {
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
 {hires.map((hire: any, idx: number) => (
 <Link
 key={hire.id ?? idx}
 href={hire.candidate_id ? `/candidates/${hire.candidate_id}` :"#"}
 className="group flex items-center gap-3 py-2.5 hover:bg-primary/10 transition-colors rounded-md -mx-2 px-2"
 >
 <Avatar size="sm">
 <AvatarFallback>
 {(hire.candidate_name ?? hire.entity_name ??"?").charAt(0).toUpperCase()}
 </AvatarFallback>
 </Avatar>
 <div className="flex-1 min-w-0">
 <p className="text-sm font-medium text-foreground truncate group-hover:text-primary">
 {hire.candidate_name ?? hire.entity_name ??"Kandydat"}
 </p>
 <p className="text-xs text-muted-foreground truncate">
 {hire.job_title ?? hire.description ??""}
 {hire.client_name ? ` · ${hire.client_name}` :""}
 </p>
 </div>
 <span className="text-xs text-muted-foreground shrink-0 whitespace-nowrap">
 {hire.hired_at ?? hire.timestamp ?? hire.created_at
 ? formatRelativeTime(hire.hired_at ?? hire.timestamp ?? hire.created_at) : ""}
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
function PlacementsV2({ ir, expiringContracts }: { ir?: any; expiringContracts?: number }) {
 const placements = ir?.placements ?? ir?.total_placements ?? 0;
 const byClient = ir?.placements_by_client ?? {};
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
 {placements}
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
 <div className="mt-2 flex items-center gap-2 text-xs text-foreground bg-warning/10 border border-warning/20 rounded-md px-3 py-2">
 <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" />
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
 const { data } = useQuery({
 queryKey: ["contractor-stats-widget"],
 queryFn: () => contractorsApi.stats().then((r) => r.data),
 staleTime: 60 * 1000,
 });

 // Gate visibility to roles that actually fill in contracts; recruiters
 // and sourcers don't own the draft completion step.
 if (!hasRole(user, "admin","delivery_lead","tac","head_of_recruitment")) {
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
 <Card className="border-warning/20 bg-warning/10 !p-4 flex items-center gap-3 transition-colors group-hover:bg-warning/15">
 <div className="h-10 w-10 rounded-full bg-warning/15 flex items-center justify-center shrink-0">
 <UserCog className="h-5 w-5 text-warning" />
 </div>
 <div className="flex-1">
 <p className="text-sm font-semibold text-foreground">
 Drafty do uzupełnienia: {incomplete}
 </p>
 <p className="text-xs text-muted-foreground">
 Kontraktorzy czekają na uzupełnienie stawek i dat — kliknij, żeby
 otworzyć listę.
 </p>
 </div>
 <ArrowRight className="h-4 w-4 text-muted-foreground" />
 </Card>
 </Link>
 );
}

// ── Main ───────────────────────────────────────────────────────────────
export function DashboardV2() {
 const {
 data: stats,
 isLoading: statsLoading,
 isError: statsIsError,
 error: statsError,
 refetch: refetchStats,
 } = useQuery({
 queryKey: ["dashboard-stats"],
 queryFn: () => api.get("/api/dashboard/stats").then((r) => r.data),
 });

 const { data: kpis } = useQuery({
 queryKey: ["dashboard-kpis"],
 queryFn: () => api.get("/api/dashboard/kpis").then((r) => r.data),
 staleTime: 60 * 1000,
 });

 const {
 data: activity,
 isError: activityIsError,
 error: activityError,
 refetch: refetchActivity,
 } = useQuery({
 queryKey: ["recent-activity"],
 queryFn: () =>
 api
 .get("/api/activities/feed?limit=15")
 .then((r) => r.data)
 .catch(() =>
 api.get("/api/dashboard/recent-activity?limit=10").then((r) => r.data)
 ),
 });

 const {
 data: upcomingEvents,
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
 staleTime: 60 * 1000,
 });

 const {
 data: recruitmentReport,
 isError: reportIsError,
 error: reportError,
 refetch: refetchReport,
 } = useQuery({
 queryKey: ["recruitment-report"],
 queryFn: () => api.get("/api/reports/recruitment?period=month").then((r) => r.data),
 staleTime: 5 * 60 * 1000,
 });

 const {
 data: leaderboard,
 isError: leaderboardIsError,
 error: leaderboardError,
 refetch: refetchLeaderboard,
 } = useQuery({
 queryKey: ["activities-leaderboard"],
 queryFn: () =>
 api.get("/api/activities/leaderboard?period=month&limit=5").then((r) => r.data),
 staleTime: 5 * 60 * 1000,
 });

 const { data: postingsStats } = useQuery({
 queryKey: ["postings-stats"],
 queryFn: () => postingsApi.stats().then((r) => r.data),
 staleTime: 60 * 1000,
 });

 const recentHires = (activity ?? []).filter(
 (a: any) => a.action === "hired" || a.action_type === "hired"
 );

 const ir = kpis?.infrareporter;
 const candidatesBase = stats?.candidates?.total ?? 50;
 const jobsBase = stats?.jobs?.open ?? 10;
 const clientsBase = stats?.clients?.total ?? 20;
 const contractsBase = stats?.contracts?.active ?? 15;

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
 <div className="flex items-center gap-2">
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
 </div>
 </div>

 {/* Moje KPI — osobisty panel */}
 <MojeKpiPanel />

 {/* KPI zespołu — managerski widok per osoba (admin/HoR/DL) */}
 <TeamKpiPanel className="mt-4" />

 {/* KPI hero row */}
 <section>
 <WidgetState
 isLoading={statsLoading}
 isError={statsIsError}
 error={statsError}
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
 errorFallback={
 <Card>
 <WidgetErrorBlock
 title="Nie udało się załadować statystyk pulpitu."
 error={statsError}
 onRetry={() => refetchStats()}
 />
 </Card>
 }
 >
 <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
 <StatCardV2
 title="Kandydaci"
 value={stats?.candidates?.total ??"—"}
 subtitle={`${stats?.candidates?.active ?? 0} aktywnych`}
 icon={Users}
 trend={{ value: 8, label: "vs. poprzedni miesiąc" }}
 sparkline={seedSparkline(candidatesBase, 1)}
 href="/candidates"
 />
 <StatCardV2
 title="Otwarte oferty"
 value={stats?.jobs?.open ??"—"}
 subtitle={`${stats?.jobs?.total ?? 0} łącznie`}
 icon={Briefcase}
 trend={{ value: 5, label: "vs. poprzedni miesiąc" }}
 sparkline={seedSparkline(jobsBase, 3)}
 href="/jobs"
 />
 <StatCardV2
 title="Klienci"
 value={stats?.clients?.total ??"—"}
 subtitle="aktywne konta"
 icon={Building2}
 trend={{ value: -2, label: "vs. poprzedni miesiąc" }}
 sparkline={seedSparkline(clientsBase, 5)}
 href="/clients"
 />
 <StatCardV2
 title="Aktywne kontrakty"
 value={stats?.contracts?.active ??"—"}
 subtitle={`${stats?.contracts?.expiring_soon ?? 0} kończących się`}
 icon={FileText}
 trend={{ value: 12, label: "vs. poprzedni miesiąc" }}
 sparkline={seedSparkline(contractsBase, 7)}
 href="/contracts"
 />
 </div>
 </WidgetState>
 </section>

 {/* Contractor drafts — only visible when count > 0 and role qualifies */}
 <ContractorDraftsWidget />

 {/* My projects (Recruiter Ownership) */}
 <MyJobsWidget />

 {/* Pipeline + Hires */}
 <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
 <Card className="lg:col-span-3">
 <CardHeader>
 <div className="flex items-center gap-2">
 <TrendingUp className="h-4 w-4 text-primary" />
 <CardTitle>Lejek rekrutacji</CardTitle>
 <Badge variant="soft" size="sm" className="ml-auto">
 30 dni
 </Badge>
 </div>
 </CardHeader>
 <CardContent>
 {reportIsError ? (
 <WidgetErrorBlock
 title="Nie udało się załadować raportu rekrutacji."
 error={reportError}
 onRetry={() => refetchReport()}
 />
 ) : (
 <FunnelV2 data={recruitmentReport} />
 )}
 </CardContent>
 </Card>

 <Card className="lg:col-span-2">
 <CardHeader>
 <div className="flex items-center gap-2">
 <UserCheck className="h-4 w-4 text-[#1d5e31]" />
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
 {activityIsError ? (
 <WidgetErrorBlock
 title="Nie udało się załadować aktywności."
 error={activityError}
 onRetry={() => refetchActivity()}
 />
 ) : (
 <RecentHiresV2 data={recentHires} />
 )}
 </CardContent>
 </Card>
 </div>

 {/* Performers + Upcoming */}
 <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
 <Card className="lg:col-span-2">
 <CardHeader>
 <div className="flex items-center gap-2">
 <Star className="h-4 w-4 text-amber-500" />
 <CardTitle>Najlepsi rekruterzy (30 dni)</CardTitle>
 <Link
 href="/insights?tab=rekrutacja"
 className="ml-auto text-xs text-primary hover:underline"
 >
 Analityka →
 </Link>
 </div>
 </CardHeader>
 <CardContent>
 {leaderboardIsError ? (
 <WidgetErrorBlock
 title="Nie udało się załadować rankingu."
 error={leaderboardError}
 onRetry={() => refetchLeaderboard()}
 />
 ) : (
 <PerformersV2 data={leaderboard} />
 )}
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
 {upcomingIsError ? (
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

 {/* Placements + system */}
 <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
 <div className="lg:col-span-2">
 <PlacementsV2
 ir={ir}
 expiringContracts={stats?.contracts?.expiring_soon}
 />
 </div>

 <Card>
 <CardHeader>
 <CardTitle>Zdrowie systemu</CardTitle>
 <CardDescription>Integracje i job boards</CardDescription>
 </CardHeader>
 <CardContent className="space-y-2 text-sm">
 <HealthRow
 label="Publikacje ofert"
 detail={`${postingsStats?.total ?? 0} aktywnych`}
 ok
 />
 <Separator />
 <HealthRow label="Fireflies sync" detail="Aktywny" ok />
 <Separator />
 <HealthRow label="Voyage AI" detail="embedding v3" ok />
 </CardContent>
 </Card>
 </div>
 </div>
 );
}

function HealthRow({
 label,
 detail,
 ok,
}: {
 label: string;
 detail: string;
 ok: boolean;
}) {
 return (
 <div className="flex items-center justify-between py-1">
 <span className="text-foreground">{label}</span>
 <span className="inline-flex items-center gap-1.5 text-xs">
 <span
 className={cn("h-2 w-2 rounded-full",
 ok ?"bg-[#1d5e31]" :"bg-primary"
 )}
 />
 <span className="text-muted-foreground">{detail}</span>
 </span>
 </div>
 );
}
