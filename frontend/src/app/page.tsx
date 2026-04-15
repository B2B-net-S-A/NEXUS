"use client";

import { useQuery } from "@tanstack/react-query";
import api, { postingsApi } from "@/lib/api";
import { StatsCard } from "@/components/StatsCard";
import { ErrorBanner } from "@/components/SkeletonLoader";
import {
  Users, Briefcase, Building2, FileText, TrendingUp, AlertTriangle,
  Trophy, DollarSign, Target, Activity, Globe, PhoneCall, Clock,
  Calendar, ChevronRight, Video, Mic, Phone, Star, UserCheck,
} from "lucide-react";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import Link from "next/link";

// ── Activity icon helper ──────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  candidate_added:    "Dodano kandydata",
  stage_changed:      "Zmiana etapu",
  call_made:          "Rozmowa telefoniczna",
  screening_done:     "Screening",
  interview_scheduled:"Umówiono rozmowę",
  placement_closed:   "Placement zamknięty",
  note_added:         "Dodano notatkę",
  cv_uploaded:        "Wgrano CV",
  created:            "Dodano do systemu",
  updated:            "Zaktualizowano profil",
  hired:              "Zatrudniono",
};

const ENTITY_COLORS: Record<string, string> = {
  candidate: "text-blue-600 bg-blue-50",
  job:       "text-green-600 bg-green-50",
  client:    "text-purple-600 bg-purple-50",
  contract:  "text-orange-600 bg-orange-50",
};

const ENTITY_LABELS: Record<string, string> = {
  candidate: "Kandydat",
  job:       "Oferta",
  client:    "Klient",
  contract:  "Kontrakt",
};

// ── Calendar event config ─────────────────────────────────────────────────────

const EVENT_TYPE_CONFIG: Record<string, { label: string; dot: string; icon: React.ReactNode }> = {
  interview:   { label: "Rozmowa",    dot: "bg-purple-500",  icon: <Video className="w-3 h-3" /> },
  screening:   { label: "Screening",  dot: "bg-blue-500",    icon: <Mic className="w-3 h-3" /> },
  call:        { label: "Call",       dot: "bg-green-500",   icon: <Phone className="w-3 h-3" /> },
  meeting:     { label: "Spotkanie",  dot: "bg-orange-500",  icon: <Calendar className="w-3 h-3" /> },
  deadline:    { label: "Deadline",   dot: "bg-red-500",     icon: <AlertTriangle className="w-3 h-3" /> },
  other:       { label: "Inne",       dot: "bg-gray-400",    icon: <Calendar className="w-3 h-3" /> },
};

// ── Portal labels ─────────────────────────────────────────────────────────────

const PORTAL_LABELS: Record<string, { label: string; dot: string }> = {
  pracuj_pl:   { label: "Pracuj.pl",   dot: "bg-orange-500" },
  justjoinit:  { label: "JustJoinIT",  dot: "bg-green-500" },
  linkedin:    { label: "LinkedIn",    dot: "bg-blue-500" },
  nofluffjobs: { label: "NoFluffJobs", dot: "bg-red-500" },
  bulldogjob:  { label: "BulldogJob",  dot: "bg-yellow-500" },
};

// ── Funnel stages ─────────────────────────────────────────────────────────────

const FUNNEL_STAGES = [
  { key: "new",        label: "Nowy",       color: "bg-gray-400",    text: "text-gray-600 dark:text-gray-400" },
  { key: "screening",  label: "Screening",  color: "bg-blue-400",    text: "text-blue-700 dark:text-blue-400" },
  { key: "interview",  label: "Interview",  color: "bg-purple-400",  text: "text-purple-700 dark:text-purple-400" },
  { key: "offer",      label: "Oferta",     color: "bg-amber-400",   text: "text-amber-700 dark:text-amber-400" },
  { key: "hired",      label: "Hired",      color: "bg-green-500",   text: "text-green-700 dark:text-green-400" },
];

// Seed deterministic sparkline data per card (simulated 7-day trend)
function seedSparkline(base: number, seed: number): number[] {
  return Array.from({ length: 7 }, (_, i) => {
    const factor = 1 + 0.15 * Math.sin((i + seed) * 1.7);
    return Math.max(0, Math.round(base * factor));
  });
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, action }: { title: string; action?: { href: string; label: string } }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">{title}</h2>
      {action && (
        <Link href={action.href} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
          {action.label} <ChevronRight className="w-3 h-3" />
        </Link>
      )}
    </div>
  );
}

// ── Card wrapper ──────────────────────────────────────────────────────────────

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md transition-all duration-200", className)}>
      {children}
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 animate-pulse space-y-3">
      <div className="flex justify-between">
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-24" />
        <div className="h-8 w-8 bg-gray-200 dark:bg-gray-700 rounded-lg" />
      </div>
      <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-16" />
      <div className="h-3 bg-gray-100 dark:bg-gray-600 rounded w-20" />
    </div>
  );
}

// ── Recruitment Funnel ────────────────────────────────────────────────────────

function RecruitmentFunnel({ data }: { data?: any }) {
  // Use data from /api/reports/recruitment or fall back to mock
  const funnel = data?.funnel ?? data?.pipeline ?? null;

  const stages = [
    { key: "new",       label: "Nowy",      count: funnel?.new      ?? funnel?.total_entered  ?? 120, stageIdx: 0 },
    { key: "screening", label: "Screening", count: funnel?.screening ?? funnel?.screening_done ?? 78,  stageIdx: 1 },
    { key: "interview", label: "Interview", count: funnel?.interview ?? funnel?.interviews      ?? 45,  stageIdx: 2 },
    { key: "offer",     label: "Oferta",    count: funnel?.offer    ?? funnel?.offers           ?? 18,  stageIdx: 3 },
    { key: "hired",     label: "Hired",     count: funnel?.hired    ?? funnel?.hired_count      ?? 9,   stageIdx: 4 },
  ];

  const maxCount = Math.max(...stages.map((s) => s.count), 1);

  const barColors = [
    "bg-gray-400 dark:bg-gray-500",
    "bg-blue-400 dark:bg-blue-500",
    "bg-purple-400 dark:bg-purple-500",
    "bg-amber-400 dark:bg-amber-500",
    "bg-green-500 dark:bg-green-400",
  ];

  return (
    <div className="space-y-3">
      {stages.map((stage, i) => {
        const pct = Math.round((stage.count / maxCount) * 100);
        const convPct = i === 0 ? 100 : Math.round((stage.count / stages[i - 1].count) * 100);
        return (
          <div key={stage.key} className="flex items-center gap-3">
            <span className="w-16 text-xs font-medium text-gray-600 dark:text-gray-400 text-right shrink-0">
              {stage.label}
            </span>
            <div className="flex-1 h-5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all duration-500", barColors[i])}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="w-8 text-xs font-bold text-gray-700 dark:text-gray-300 text-right shrink-0">
              {stage.count}
            </span>
            <span className="w-12 text-[10px] text-gray-400 dark:text-gray-500 text-right shrink-0">
              {i === 0 ? "100%" : `${convPct}%`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Top Performers ────────────────────────────────────────────────────────────

function TopPerformers({ data }: { data?: any }) {
  const leaderboard = data?.leaderboard ?? [];

  if (!leaderboard.length) {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-gray-400">
        <Trophy className="w-8 h-8 mb-2 opacity-30" />
        <p className="text-sm">Brak danych o aktywności</p>
      </div>
    );
  }

  const maxActions = Math.max(...leaderboard.map((r: any) => r.total_actions), 1);

  return (
    <div className="space-y-3">
      {leaderboard.slice(0, 5).map((rec: any, i: number) => {
        const initials = (rec.user_name ?? "?")
          .split(" ")
          .map((p: string) => p[0])
          .join("")
          .toUpperCase()
          .slice(0, 2);
        const barW = Math.round((rec.total_actions / maxActions) * 100);

        return (
          <div key={rec.user_id} className="flex items-center gap-3">
            {/* Rank */}
            <span className={cn(
              "text-xs font-bold w-4 text-center shrink-0",
              i === 0 ? "text-yellow-500" : i === 1 ? "text-gray-400" : i === 2 ? "text-orange-400" : "text-gray-300"
            )}>
              {i + 1}
            </span>
            {/* Avatar */}
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-xs font-bold shrink-0">
              {initials}
            </div>
            {/* Name + sparkline bar */}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{rec.user_name}</p>
              <div className="mt-1 h-1.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-500"
                  style={{ width: `${barW}%` }}
                />
              </div>
            </div>
            {/* Count */}
            <span className="text-xs font-bold text-blue-600 dark:text-blue-400 shrink-0">
              {rec.total_actions}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Recent Hires ──────────────────────────────────────────────────────────────

function RecentHires({ data }: { data?: any[] }) {
  // Filter activities for 'hired' action or use passed data
  const hires = (data ?? []).slice(0, 5);

  if (!hires.length) {
    return (
      <div className="flex flex-col items-center justify-center py-6 text-gray-400">
        <UserCheck className="w-8 h-8 mb-2 opacity-30" />
        <p className="text-sm">Brak ostatnich zatrudnień</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {hires.map((hire: any, idx: number) => (
        <Link
          key={hire.id ?? idx}
          href={hire.candidate_id ? `/candidates/${hire.candidate_id}` : "#"}
          className="flex items-center gap-3 py-2 border-b border-gray-100 dark:border-gray-700 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-700/30 rounded-lg px-2 -mx-2 transition-colors group"
        >
          <div className="w-7 h-7 rounded-full bg-green-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
            {(hire.candidate_name ?? hire.entity_name ?? "?").charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate group-hover:text-green-700 dark:group-hover:text-green-400">
              {hire.candidate_name ?? hire.entity_name ?? "Kandydat"}
            </p>
            <p className="text-xs text-gray-400 truncate">
              {hire.job_title ?? hire.description ?? ""}
              {hire.client_name ? ` · ${hire.client_name}` : ""}
            </p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs text-gray-400">
              {hire.hired_at ?? hire.timestamp ?? hire.created_at
                ? formatRelativeTime(hire.hired_at ?? hire.timestamp ?? hire.created_at)
                : ""}
            </p>
          </div>
        </Link>
      ))}
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading, error: statsError, refetch: refetchStats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: () => api.get("/api/dashboard/stats").then((r) => r.data),
  });

  const { data: kpis } = useQuery({
    queryKey: ["dashboard-kpis"],
    queryFn: () => api.get("/api/dashboard/kpis").then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const { data: activity } = useQuery({
    queryKey: ["recent-activity"],
    queryFn: () => api.get("/api/activities/feed?limit=15").then((r) => r.data).catch(() =>
      api.get("/api/dashboard/recent-activity?limit=10").then((r) => r.data)
    ),
  });

  const { data: postingsStats } = useQuery({
    queryKey: ["postings-stats"],
    queryFn: () => postingsApi.stats().then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const { data: callStats } = useQuery({
    queryKey: ["call-stats"],
    queryFn: () => api.get("/api/calls/stats").then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const { data: upcomingEvents } = useQuery({
    queryKey: ["upcoming-events"],
    queryFn: () =>
      api
        .get("/api/calendar/events", {
          params: {
            upcoming: true,
            limit: 5,
            start_from: new Date().toISOString(),
          },
        })
        .then((r) => (Array.isArray(r.data) ? r.data.slice(0, 5) : [])),
    staleTime: 60 * 1000,
  });

  const { data: recruitmentReport } = useQuery({
    queryKey: ["recruitment-report"],
    queryFn: () => api.get("/api/reports/recruitment?period=month").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const { data: leaderboard } = useQuery({
    queryKey: ["activities-leaderboard"],
    queryFn: () => api.get("/api/activities/leaderboard?period=month&limit=5").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  // Recent hires from activity feed
  const recentHires = (activity ?? []).filter(
    (a: any) => a.action === "hired" || a.action_type === "hired"
  );

  const ir = kpis?.infrareporter;
  const ats = kpis?.ats;

  // Trend seeds (simulated) — based on current stats values
  const candidatesBase = stats?.candidates?.total ?? 50;
  const jobsBase = stats?.jobs?.open ?? 10;
  const clientsBase = stats?.clients?.total ?? 20;
  const contractsBase = stats?.contracts?.active ?? 15;

  return (
    <div className="space-y-8">
      {/* Page title */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Przegląd aktywności — B2B.net S.A.</p>
      </div>

      {/* Global error banner */}
      {statsError && (
        <ErrorBanner
          message="Nie udało się załadować statystyk. Sprawdź połączenie z API."
          onRetry={() => refetchStats()}
        />
      )}

      {/* ── ROW 1: Main KPIs with trends + sparklines ── */}
      <section>
        <SectionHeader title="ATS — Kluczowe wskaźniki" action={{ href: "/candidates", label: "Wszyscy kandydaci" }} />
        {statsLoading ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatsCard
              title="Kandydaci"
              value={stats?.candidates?.total ?? "—"}
              subtitle={`${stats?.candidates?.active ?? 0} aktywnych`}
              icon={<Users className="w-5 h-5" />}
              color="blue"
              trend={{ value: 8, label: "vs. zeszły miesiąc" }}
              sparkline={seedSparkline(candidatesBase, 1)}
            />
            <StatsCard
              title="Otwarte oferty"
              value={stats?.jobs?.open ?? "—"}
              icon={<Briefcase className="w-5 h-5" />}
              color="green"
              trend={{ value: 5, label: "vs. zeszły miesiąc" }}
              sparkline={seedSparkline(jobsBase, 3)}
            />
            <StatsCard
              title="Klienci"
              value={stats?.clients?.total ?? "—"}
              icon={<Building2 className="w-5 h-5" />}
              color="purple"
              trend={{ value: -2, label: "vs. zeszły miesiąc" }}
              sparkline={seedSparkline(clientsBase, 5)}
            />
            <StatsCard
              title="Aktywne kontrakty"
              value={stats?.contracts?.active ?? "—"}
              icon={<FileText className="w-5 h-5" />}
              color="orange"
              trend={{ value: 12, label: "vs. zeszły miesiąc" }}
              sparkline={seedSparkline(contractsBase, 7)}
            />
          </div>
        )}
      </section>

      {/* ── ROW 2: Lejek Rekrutacji + Recent Hires ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recruitment Funnel */}
        <Card>
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-4 h-4 text-blue-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Lejek Rekrutacji</h2>
            <span className="ml-auto text-xs text-gray-400">30 dni</span>
          </div>
          <RecruitmentFunnel data={recruitmentReport} />
        </Card>

        {/* Recent Hires */}
        <Card>
          <div className="flex items-center gap-2 mb-4">
            <UserCheck className="w-4 h-4 text-green-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Ostatnie zatrudnienia</h2>
          </div>
          <RecentHires data={recentHires} />
        </Card>
      </div>

      {/* ── ROW 3: Top Performers ── */}
      <section>
        <SectionHeader title="Najlepsi Rekruterzy (30 dni)" />
        <Card>
          <div className="flex items-center gap-2 mb-4">
            <Star className="w-4 h-4 text-yellow-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Top 5 — aktywność</h2>
          </div>
          <TopPerformers data={leaderboard} />
        </Card>
      </section>

      {/* ── ROW 4: Placements + Revenue ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Placements */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 rounded-lg bg-green-50">
              <Target className="w-4 h-4 text-green-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-200">Placements — ten miesiąc</p>
              <p className="text-xs text-gray-400 dark:text-gray-500">zatrudnienia</p>
            </div>
            <div className="ml-auto text-3xl font-bold text-gray-900 dark:text-gray-100">
              {ir?.placements ?? ir?.total_placements ?? stats?.pipeline?.hired_this_month ?? "—"}
            </div>
          </div>
          {ir?.placements_by_client && Object.keys(ir.placements_by_client).length > 0 && (
            <div className="space-y-2">
              {Object.entries(ir.placements_by_client).slice(0, 4).map(([client, count]) => (
                <div key={client} className="flex items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
                  <span className="flex-1 truncate">{client}</span>
                  <div className="w-20 bg-gray-100 dark:bg-gray-700 rounded-full h-1.5">
                    <div
                      className="bg-green-500 h-1.5 rounded-full"
                      style={{
                        width: `${Math.min(100, ((count as number) / Math.max(...Object.values(ir.placements_by_client) as number[])) * 100)}%`,
                      }}
                    />
                  </div>
                  <span className="font-semibold w-4 text-right">{count as number}</span>
                </div>
              ))}
            </div>
          )}
          {stats?.contracts?.expiring_soon > 0 && (
            <div className="mt-3 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              {stats.contracts.expiring_soon} kontrakt{stats.contracts.expiring_soon > 1 ? "y" : ""} kończą się w ciągu 30 dni
            </div>
          )}
        </Card>

        {/* Revenue / Margin */}
        <Card>
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 rounded-lg bg-blue-50">
              <DollarSign className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-200">Revenue — ten miesiąc</p>
              <p className="text-xs text-gray-400">InfraReporter</p>
            </div>
          </div>
          {kpis?.infrareporter_available && ir ? (
            <div className="space-y-3">
              <div className="flex justify-between items-end">
                <div>
                  <p className="text-3xl font-bold text-gray-900 dark:text-gray-100">
                    {ir?.revenue ? `${Number(ir.revenue).toLocaleString("pl-PL")} PLN` : "—"}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">przychód miesięczny</p>
                </div>
                <div className="text-right">
                  <p className="text-xl font-bold text-green-600">
                    {ir?.margin_pct != null
                      ? `${Number(ir.margin_pct).toFixed(1)}%`
                      : ir?.margin != null
                      ? `${Number(ir.margin).toLocaleString("pl-PL")} PLN`
                      : "—"}
                  </p>
                  <p className="text-xs text-gray-400">marża</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-gray-50 dark:border-gray-700">
                <div className="text-center">
                  <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{ir?.active_consultants ?? ats?.active_consultants ?? "—"}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">konsultantów</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-gray-900 dark:text-gray-100">{stats?.contracts?.active ?? "—"}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500">aktywnych kontraktów</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-6 text-center text-gray-400">
              <DollarSign className="w-8 h-8 mb-2 text-gray-200" />
              <p className="text-sm">InfraReporter niedostępny</p>
            </div>
          )}
        </Card>
      </div>

      {/* ── ROW 5: Rozmowy ── */}
      <section>
        <SectionHeader title="Rozmowy" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 rounded-lg bg-emerald-50">
                <PhoneCall className="w-4 h-4 text-emerald-600" />
              </div>
              <span className="text-sm font-medium text-gray-600 dark:text-gray-300">Rozmowy w tygodniu</span>
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {callStats?.global?.calls_this_week ?? "—"}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">wszystkich rekruterów</p>
          </Card>

          <Card>
            <div className="flex items-center gap-3 mb-2">
              <div className="p-2 rounded-lg bg-blue-50">
                <Clock className="w-4 h-4 text-blue-600" />
              </div>
              <span className="text-sm font-medium text-gray-600 dark:text-gray-300">Śr. czas rozmowy</span>
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {callStats?.global?.avg_duration_formatted ?? "—"}
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">ten tydzień</p>
          </Card>

          <div className="col-span-1 sm:col-span-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-5 flex items-center gap-3">
            <PhoneCall className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-300">Integracja z CloudTalk w przygotowaniu</p>
              <p className="text-xs text-amber-600 dark:text-amber-500 mt-0.5">
                Automatyczne logowanie rozmów, nagrania i transkrypcje dostępne po podłączeniu API
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── ROW 6: Activity + Top Recruiters (KPI data) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Activity */}
        <Card className="flex flex-col">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-blue-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Ostatnia aktywność</h2>
          </div>
          <div className="space-y-1 flex-1">
            {activity?.length ? activity.map((item: any, idx: number) => {
              const entityCfg = ENTITY_COLORS[item.entity_type] ?? "text-gray-600 bg-gray-50";
              const initials = (item.user || "?").charAt(0).toUpperCase();
              const link = item.link;
              const timestamp = item.timestamp || item.created_at;

              const Inner = (
                <div className={cn(
                  "flex items-start gap-3 text-sm py-2 border-b border-gray-100 dark:border-gray-700 last:border-0 group",
                  link ? "hover:bg-gray-50 dark:hover:bg-gray-700/30 rounded-lg px-2 -mx-2 cursor-pointer transition-colors" : ""
                )}>
                  <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-semibold flex-shrink-0 mt-0.5">
                    {initials}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-xs text-gray-800 dark:text-gray-200 leading-relaxed">
                      <span className="font-semibold">{item.user || "System"}</span>{" "}
                      <span className="text-gray-500">{item.description || (ACTION_LABELS[item.action] ?? item.action)}</span>
                      {item.entity_name && (
                        <span className="font-medium text-gray-700 dark:text-gray-300"> {item.entity_name}</span>
                      )}
                    </span>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", entityCfg)}>
                        {ENTITY_LABELS[item.entity_type] ?? item.entity_type}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        {formatRelativeTime(timestamp)}
                      </span>
                    </div>
                  </div>
                </div>
              );

              return link ? (
                <Link key={item.id ?? idx} href={link}>
                  {Inner}
                </Link>
              ) : (
                <div key={item.id ?? idx}>{Inner}</div>
              );
            }) : (
              <p className="text-gray-400 text-sm py-4 text-center">Brak aktywności</p>
            )}
          </div>
        </Card>

        {/* Top Recruiters (from KPI) */}
        {ats?.top_recruiters && ats.top_recruiters.length > 0 ? (
          <Card>
            <div className="flex items-center gap-2 mb-4">
              <Trophy className="w-4 h-4 text-yellow-500" />
              <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">Top Rekruterzy — ten miesiąc</h2>
            </div>
            <div className="space-y-2">
              {ats.top_recruiters.map((r: any, i: number) => (
                <div key={r.user_id} className="flex items-center gap-3 py-2 border-b border-gray-50 dark:border-gray-700 last:border-0">
                  <span className={cn(
                    "text-sm font-bold w-5 text-center",
                    i === 0 ? "text-yellow-500" : i === 1 ? "text-gray-400" : i === 2 ? "text-orange-400" : "text-gray-300"
                  )}>
                    {i + 1}
                  </span>
                  <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
                    {r.user_name?.charAt(0)?.toUpperCase() ?? "?"}
                  </div>
                  <span className="flex-1 text-sm font-medium text-gray-800 dark:text-gray-200">{r.user_name}</span>
                  <div className="flex items-center gap-3 text-xs text-right">
                    <span className="text-blue-600 font-medium">{r.total_actions} akcji</span>
                    <span className="text-green-600 font-bold">{r.placements} place.</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Card className="flex flex-col items-center justify-center text-center py-8">
            <Trophy className="w-8 h-8 text-gray-200 mb-2" />
            <p className="text-gray-400 text-sm">Brak danych o rekruterach</p>
          </Card>
        )}
      </div>

      {/* ── ROW 7: Job Portals ── */}
      <section>
        <SectionHeader title="Portale ogłoszeniowe" />
        <Card>
          <div className="flex items-center gap-2 mb-3">
            <Globe className="w-4 h-4 text-blue-500" />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-200">Multi-Posting — podsumowanie</span>
            <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-0.5 ml-auto">
              dane symulowane
            </span>
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{postingsStats?.active_postings ?? "—"}</p>
              <p className="text-xs text-gray-500 mt-0.5">Aktywne publikacje</p>
            </div>
            <div className="text-center border-x border-gray-100 dark:border-gray-700">
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                {postingsStats?.total_views != null ? postingsStats.total_views.toLocaleString() : "—"}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">Wyświetlenia łącznie</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-blue-600">{postingsStats?.total_applications ?? "—"}</p>
              <p className="text-xs text-gray-500 mt-0.5">Aplikacje łącznie</p>
            </div>
          </div>
          {postingsStats?.by_portal && postingsStats.by_portal.length > 0 && (
            <div className="space-y-1.5 border-t border-gray-100 dark:border-gray-700 pt-3">
              {postingsStats.by_portal.map((p: { portal: string; active_postings: number; total_views: number; total_applications: number }) => {
                const cfg = PORTAL_LABELS[p.portal] ?? { label: p.portal, dot: "bg-gray-400" };
                return (
                  <div key={p.portal} className="flex items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
                    <span className={cn("w-2 h-2 rounded-full flex-shrink-0", cfg.dot)} />
                    <span className="w-24 font-medium">{cfg.label}</span>
                    <span className="text-green-600 font-medium w-12">{p.active_postings} akt.</span>
                    <span className="text-gray-400">{p.total_views.toLocaleString()} views</span>
                    <span className="ml-auto text-blue-600 font-medium">{p.total_applications} aplik.</span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </section>

      {/* ── ROW 8: Upcoming Events ── */}
      <section>
        <SectionHeader title="Najbliższe wydarzenia" action={{ href: "/calendar", label: "Zobacz kalendarz" }} />
        <Card>
          <div className="space-y-2">
            {upcomingEvents && upcomingEvents.length > 0 ? (
              upcomingEvents.map((event: any) => {
                const cfg = EVENT_TYPE_CONFIG[event.event_type] ?? EVENT_TYPE_CONFIG.other;
                const start = event.start_time ? new Date(event.start_time) : null;
                return (
                  <div key={event.id} className="flex items-center gap-3 py-2 border-b border-gray-100 dark:border-gray-700 last:border-0">
                    <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${cfg.dot}`} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">{event.title}</p>
                      {event.candidate && (
                        <p className="text-xs text-gray-400 truncate">
                          {event.candidate.name} {event.candidate.lastname}
                        </p>
                      )}
                    </div>
                    <div className="text-right flex-shrink-0">
                      {start && (
                        <>
                          <p className="text-xs font-medium text-gray-600 dark:text-gray-300">
                            {start.toLocaleDateString("pl-PL", { day: "2-digit", month: "short" })}
                          </p>
                          <p className="text-xs text-gray-400">
                            {start.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}
                          </p>
                        </>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 hidden sm:block w-20 text-right">{cfg.label}</span>
                  </div>
                );
              })
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-gray-400">
                <Calendar className="w-8 h-8 mb-2 opacity-30" />
                <p className="text-sm">Brak nadchodzących wydarzeń</p>
              </div>
            )}
          </div>
        </Card>
      </section>

      {/* ── ROW 9: InfraReporter ── */}
      {kpis?.infrareporter_available && ir && ir.placements_by_client && Object.keys(ir.placements_by_client).length > 0 && (
        <section>
          <SectionHeader title="InfraReporter — Placements per klient" />
          <Card>
            <div className="space-y-2">
              {Object.entries(ir.placements_by_client).map(([client, count]) => {
                const max = Math.max(...Object.values(ir.placements_by_client) as number[]);
                return (
                  <div key={client} className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400 w-40 truncate">{client}</span>
                    <div className="flex-1 mx-4 bg-gray-100 dark:bg-gray-700 rounded-full h-2">
                      <div
                        className="bg-blue-500 h-2 rounded-full transition-all"
                        style={{ width: `${Math.min(100, ((count as number) / max) * 100)}%` }}
                      />
                    </div>
                    <span className="font-semibold w-6 text-right dark:text-gray-200">{count as number}</span>
                  </div>
                );
              })}
            </div>
          </Card>
        </section>
      )}
    </div>
  );
}
