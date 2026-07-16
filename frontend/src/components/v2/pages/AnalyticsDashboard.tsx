"use client";

/**
 * Analytics v1 — dashboard z widokami per rola (plan PR 5).
 *
 * Routing: /dashboard?view=operations|recruitment|delivery|executive&period=…
 * - URL jest JEDYNYM źródłem prawdy okresu i widoku (back/forward działa),
 * - default view wg priorytetu: admin → HoR → DL → TAC → recruiter/sourcer → user,
 * - przełącznik widoków tylko gdy user ma dostęp do >1 widoku,
 * - panel bez capability nie renderuje się ANI nie pyta API (fail-closed),
 * - dane wyłącznie z /api/analytics/v1 (koperta §4.5, StatsBoundary).
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Briefcase,
  Building2,
  Handshake,
  Phone,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  StatsBoundary,
  deriveBoundaryState,
} from "@/components/v2/dashboard/StatsBoundary";
import {
  CAP,
  canQueryAnalytics,
  statsApi,
  type PeriodParams,
} from "@/lib/stats-api";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

// ── Widoki i dostęp ─────────────────────────────────────────────────────────

export type DashboardView =
  | "operations"
  | "recruitment"
  | "delivery"
  | "executive";

const VIEW_CAPABILITY: Record<DashboardView, string> = {
  operations: CAP.OPERATIONAL_AGGREGATES,
  recruitment: CAP.OWN_RECRUITMENT_KPI,
  delivery: CAP.CLIENT_OPERATIONS,
  executive: CAP.FINANCE,
};

const VIEW_LABEL: Record<DashboardView, string> = {
  operations: "Operacje",
  recruitment: "Rekrutacja",
  delivery: "Delivery",
  executive: "Zarząd",
};

/** Priorytet default view (plan §PR5): admin → HoR → DL → TAC → rekruter → user. */
export function defaultViewFor(user: {
  role?: string;
  roles?: string[];
  analytics_capabilities?: string[];
}): DashboardView {
  const roles = new Set([user.role, ...(user.roles ?? [])].filter(Boolean));
  if (roles.has("admin")) return "executive";
  if (roles.has("head_of_recruitment")) return "recruitment";
  if (roles.has("delivery_lead")) return "delivery";
  if (roles.has("tac")) return "delivery";
  if (roles.has("recruiter") || roles.has("sourcer")) return "recruitment";
  return "operations";
}

const PERIODS: Array<{ value: NonNullable<PeriodParams["period"]>; label: string }> = [
  { value: "day", label: "Dziś" },
  { value: "week", label: "Tydzień" },
  { value: "month", label: "Miesiąc" },
  { value: "quarter", label: "Kwartał" },
  { value: "year", label: "Rok" },
];

// ── Małe klocki UI ──────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </p>
        <span className="inline-flex items-center justify-center h-7 w-7 rounded-md bg-primary/10 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>
      <div className="font-semibold text-2xl text-foreground leading-none">{value}</div>
    </Card>
  );
}

function BarsRow({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-32 truncate text-foreground">{label}</span>
      <div className="flex-1 rounded-full bg-[hsl(var(--border))]/60 h-1.5 overflow-hidden">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${max ? Math.min(100, (value / max) * 100) : 0}%` }}
        />
      </div>
      <span className="w-8 text-right font-semibold text-foreground">{value}</span>
    </div>
  );
}

function useEnvelopeQuery<T>(
  key: unknown[],
  capability: string,
  fetcher: () => Promise<import("@/lib/stats-api").AnalyticsEnvelope<T>>
) {
  const allowed = canQueryAnalytics(capability);
  const q = useQuery({
    queryKey: key,
    queryFn: fetcher,
    enabled: allowed,
    staleTime: 60_000,
  });
  const errorStatus = (q.error as { response?: { status?: number } } | null)?.response
    ?.status;
  return {
    ...q,
    allowed,
    boundary: deriveBoundaryState({
      allowed,
      isLoading: q.isLoading && allowed,
      isFetching: q.isFetching,
      isError: q.isError,
      errorStatus,
      quality: q.data?.quality,
    }),
  };
}

// ── Panele ──────────────────────────────────────────────────────────────────

const FUNNEL_LABELS: Record<string, string> = {
  verified: "Weryfikacje",
  cv_sent: "Rekomendacje",
  interview: "Interview",
  client_interview: "Interview klienta",
  hired: "Placementy",
};

function OperationsView({ period }: { period: PeriodParams }) {
  const overview = useEnvelopeQuery(
    ["an-overview", period],
    CAP.OPERATIONAL_AGGREGATES,
    () => statsApi.overview(period)
  );
  const funnel = useEnvelopeQuery(
    ["an-funnel", period],
    CAP.OPERATIONAL_AGGREGATES,
    () => statsApi.recruitmentFunnel(period)
  );
  const pipeline = useEnvelopeQuery(
    ["an-pipeline", period],
    CAP.OPERATIONAL_AGGREGATES,
    () => statsApi.pipelineSnapshot(period)
  );

  const d = overview.data?.data;
  return (
    <div className="space-y-4">
      <StatsBoundary
        state={overview.boundary}
        warnings={overview.data?.quality.warnings}
        onRetry={() => overview.refetch()}
      >
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <Stat label="Kandydaci" value={d?.candidates.total ?? "—"} icon={Users} />
          <Stat
            label="Oferty (otwarte)"
            value={d ? `${d.jobs.open} / ${d.jobs.total}` : "—"}
            icon={Briefcase}
          />
          <Stat
            label="Klienci (aktywni)"
            value={d ? `${d.clients.active} / ${d.clients.total}` : "—"}
            icon={Building2}
          />
          <Stat label="Aktywne kontrakty" value={d?.contracts.active ?? "—"} icon={Handshake} />
          <Stat
            label="Placementy w okresie"
            value={d?.placements_in_period ?? "—"}
            icon={Target}
          />
        </div>
      </StatsBoundary>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Lejek (pierwsze osiągnięcia)</CardTitle>
            <CardDescription>raz per kandydat × oferta</CardDescription>
          </CardHeader>
          <CardContent>
            <StatsBoundary state={funnel.boundary} onRetry={() => funnel.refetch()}>
              <div className="space-y-2">
                {Object.entries(funnel.data?.data.funnel ?? {}).map(([stage, cnt]) => {
                  const max = Math.max(
                    1,
                    ...Object.values(funnel.data?.data.funnel ?? {})
                  );
                  return (
                    <BarsRow
                      key={stage}
                      label={FUNNEL_LABELS[stage] ?? stage}
                      value={cnt}
                      max={max}
                    />
                  );
                })}
              </div>
            </StatsBoundary>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Aktualny pipeline</CardTitle>
            <CardDescription>ostatni etap per kandydat × oferta</CardDescription>
          </CardHeader>
          <CardContent>
            <StatsBoundary state={pipeline.boundary} onRetry={() => pipeline.refetch()}>
              <div className="space-y-2">
                {Object.entries(pipeline.data?.data.stages ?? {})
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([stage, cnt]) => {
                    const max = Math.max(
                      1,
                      ...Object.values(pipeline.data?.data.stages ?? {})
                    );
                    return <BarsRow key={stage} label={stage} value={cnt} max={max} />;
                  })}
              </div>
            </StatsBoundary>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function RecruitmentView({ period }: { period: PeriodParams }) {
  const { user } = useAuthStore();
  const me = useEnvelopeQuery(["an-me-kpis", period], CAP.OWN_RECRUITMENT_KPI, () =>
    statsApi.myKpis(period)
  );
  const sources = useEnvelopeQuery(
    ["an-sources", period],
    CAP.OPERATIONAL_AGGREGATES,
    () => statsApi.sources(period)
  );
  const canTeam = hasAnalyticsCapability(user, CAP.TEAM_KPI);
  const team = useEnvelopeQuery(["an-team-kpis", period], CAP.TEAM_KPI, () =>
    statsApi.teamKpis(period)
  );

  const k = me.data?.data;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Moje KPI (kanoniczne)</CardTitle>
          <CardDescription>
            atrybucja: pierwszy weryfikator pary kandydat × oferta
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StatsBoundary
            state={me.boundary}
            warnings={me.data?.quality.warnings}
            onRetry={() => me.refetch()}
          >
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              <Stat label="Rozmowy" value={k?.completed_calls ?? "—"} icon={Phone} />
              <Stat
                label="Weryfikacje"
                value={k?.first_verifications ?? "—"}
                icon={Users}
              />
              <Stat
                label="Nowi kandydaci"
                value={k?.candidates_added ?? "—"}
                icon={Users}
              />
              <Stat
                label="Rekomendacje"
                value={k?.first_recommendations ?? "—"}
                icon={TrendingUp}
              />
              <Stat
                label="Placementy"
                value={k?.first_placements ?? "—"}
                icon={Target}
              />
            </div>
          </StatsBoundary>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Źródła (first-touch)</CardTitle>
            <CardDescription>distinct kandydaci; hire rate ≤ 100%</CardDescription>
          </CardHeader>
          <CardContent>
            <StatsBoundary state={sources.boundary} onRetry={() => sources.refetch()}>
              <div className="space-y-2">
                {(sources.data?.data.sources ?? []).slice(0, 8).map((s) => (
                  <div key={s.channel} className="flex items-center gap-3 text-xs">
                    <span className="w-32 truncate text-foreground">{s.channel}</span>
                    <span className="flex-1 text-muted-foreground">
                      {s.candidates} kandydatów
                    </span>
                    <Badge variant="soft" size="sm">
                      {s.hired} hired · {s.hire_rate_pct}%
                    </Badge>
                  </div>
                ))}
              </div>
            </StatsBoundary>
          </CardContent>
        </Card>

        {canTeam && (
          <Card>
            <CardHeader>
              <CardTitle>KPI zespołu</CardTitle>
              <CardDescription>suma wierszy = totals (parity §8)</CardDescription>
            </CardHeader>
            <CardContent>
              <StatsBoundary
                state={team.boundary}
                warnings={team.data?.quality.warnings}
                onRetry={() => team.refetch()}
              >
                <div className="space-y-1.5">
                  {(team.data?.data.rows ?? []).slice(0, 8).map((r) => (
                    <div key={r.user_id} className="flex items-center gap-2 text-xs">
                      <span className="w-36 truncate text-foreground">{r.user_name}</span>
                      <span className="text-muted-foreground">
                        W:{r.first_verifications} R:{r.first_recommendations} P:
                        {r.first_placements}
                      </span>
                    </div>
                  ))}
                </div>
              </StatsBoundary>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function DeliveryView({ period }: { period: PeriodParams }) {
  const { user } = useAuthStore();
  const overview = useEnvelopeQuery(
    ["an-overview", period],
    CAP.OPERATIONAL_AGGREGATES,
    () => statsApi.overview(period)
  );
  const tenders = useEnvelopeQuery(
    ["an-tenders", period],
    CAP.TENDERS_OPERATIONAL,
    () => statsApi.tenders(period)
  );
  const showsValues = hasAnalyticsCapability(user, CAP.FINANCE);

  const d = overview.data?.data;
  return (
    <div className="space-y-4">
      <StatsBoundary state={overview.boundary} onRetry={() => overview.refetch()}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat
            label="Klienci (aktywni)"
            value={d ? `${d.clients.active} / ${d.clients.total}` : "—"}
            icon={Building2}
          />
          <Stat label="Aktywne kontrakty" value={d?.contracts.active ?? "—"} icon={Handshake} />
          <Stat
            label="Kończące się (30 dni)"
            value={d?.contracts.expiring_30d ?? "—"}
            icon={BarChart3}
          />
          <Stat
            label="Placementy w okresie"
            value={d?.placements_in_period ?? "—"}
            icon={Target}
          />
        </div>
      </StatsBoundary>

      <Card>
        <CardHeader>
          <CardTitle>Przetargi</CardTitle>
          <CardDescription>
            wynik z Job.close_reason{!showsValues && " · kwoty ukryte (brak VIEW_FINANCE)"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StatsBoundary state={tenders.boundary} onRetry={() => tenders.refetch()}>
            <div className="flex flex-wrap gap-2">
              {(tenders.data?.data.outcomes ?? []).map((o) => (
                <Badge key={o.outcome} variant="soft" size="sm">
                  {o.outcome}: {o.count}
                  {showsValues && o.salary_max_sum ? ` · ${o.salary_max_sum} PLN` : ""}
                </Badge>
              ))}
              {tenders.data && (
                <Badge variant="soft" size="sm">
                  win rate: {tenders.data.data.win_rate_pct}%
                </Badge>
              )}
            </div>
          </StatsBoundary>
        </CardContent>
      </Card>
    </div>
  );
}

function ExecutiveView({ period }: { period: PeriodParams }) {
  const board = useEnvelopeQuery(["an-exec-board", period], CAP.FINANCE, () =>
    statsApi.executiveBoard(period)
  );
  const d = board.data?.data;
  return (
    <div className="space-y-4">
      <StatsBoundary
        state={board.boundary}
        warnings={board.data?.quality.warnings}
        onRetry={() => board.refetch()}
      >
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat
            label="MRR (PLN)"
            value={d?.finance.mrr ?? "—"}
            icon={TrendingUp}
          />
          <Stat
            label="Marża/mc (PLN)"
            value={d?.finance.monthly_margin ?? "—"}
            icon={BarChart3}
          />
          <Stat
            label="Marża %"
            value={d?.finance.margin_pct != null ? `${d.finance.margin_pct}%` : "—"}
            icon={BarChart3}
          />
          <Stat
            label="Aktywne kontrakty"
            value={d?.finance.active_contracts ?? "—"}
            icon={Handshake}
          />
        </div>
        <div className="mt-4 grid grid-cols-2 lg:grid-cols-5 gap-3">
          {Object.entries(d?.funnel ?? {}).map(([stage, cnt]) => (
            <Stat
              key={stage}
              label={FUNNEL_LABELS[stage] ?? stage}
              value={cnt}
              icon={Users}
            />
          ))}
        </div>
      </StatsBoundary>
    </div>
  );
}

// ── Główny komponent ────────────────────────────────────────────────────────

export function AnalyticsDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, hydrated } = useAuthStore();

  const available = React.useMemo(() => {
    const views = (Object.keys(VIEW_CAPABILITY) as DashboardView[]).filter((v) =>
      hasAnalyticsCapability(user, VIEW_CAPABILITY[v])
    );
    return views;
  }, [user]);

  const urlView = searchParams.get("view") as DashboardView | null;
  const view: DashboardView =
    urlView && available.includes(urlView)
      ? urlView
      : user
        ? defaultViewFor(user)
        : "operations";

  const urlPeriod = searchParams.get("period");
  const period: PeriodParams = {
    period: (PERIODS.some((p) => p.value === urlPeriod)
      ? urlPeriod
      : "month") as PeriodParams["period"],
  };

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set(key, value);
    router.push(`/dashboard?${next.toString()}`);
  };

  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }
  if (!user) {
    return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-5">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
            Analytics v1
          </p>
          <h1 className="font-semibold text-3xl tracking-[-0.02em] text-foreground mt-1">
            Dashboard · {VIEW_LABEL[view]}
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Przełącznik widoków — tylko gdy user ma >1 widok */}
          {available.length > 1 && (
            <div className="inline-flex rounded-lg border border-[hsl(var(--border))] p-0.5">
              {available.map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setParam("view", v)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium",
                    v === view
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {VIEW_LABEL[v]}
                </button>
              ))}
            </div>
          )}
          <div className="inline-flex rounded-lg border border-[hsl(var(--border))] p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => setParam("period", p.value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium",
                  p.value === period.period
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <Link href="/" className="text-xs text-primary hover:underline">
            Klasyczny dashboard →
          </Link>
        </div>
      </div>

      {view === "operations" && <OperationsView period={period} />}
      {view === "recruitment" && <RecruitmentView period={period} />}
      {view === "delivery" && <DeliveryView period={period} />}
      {view === "executive" && <ExecutiveView period={period} />}
    </div>
  );
}
