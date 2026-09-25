"use client";

// Publiczny harness nowego Insights (24.09.2026): pięć widoków na danych
// FIKCYJNYCH, ZERO zapytań — każdy klucz jest zasiany, a interceptor odcina
// sieć (pilnuje `harness-seeds.test.ts`). Widoki renderowane wprost, nie przez
// `InsightsView`: ten przepisuje adres na `/insights`, czyli wyszedłby
// z podglądu. Zmiana okresu w podglądzie prowadzi na `/insights` — nie klikaj.
//
// `?as=recruiter|hor|admin` wybiera rolę, `?view=` widok, `?report=` raport.

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { FirmaView, FIRMA_DEFAULT_PERIOD } from "@/components/insights/views/FirmaView";
import { MojMiesiacView } from "@/components/insights/views/MojMiesiacView";
import { RaportyView } from "@/components/insights/views/RaportyView";
import { RywalizacjaView } from "@/components/insights/views/RywalizacjaView";
import {
  ZespolView,
  ZESPOL_DEFAULT_PERIOD,
  ZESPOL_DL_PERIOD,
} from "@/components/insights/views/ZespolView";
import { api } from "@/lib/api";
import { insightsCampaignQueryKeys } from "@/lib/insights-campaign-api";
import { insightsQueryKeys, type InsightsPeriodParams } from "@/lib/insights-api";
import { performanceFlagsQueryKey } from "@/lib/insights-flags-api";
import { isReportId } from "@/lib/insights-reports";
import {
  insightsTeamQueryKeys,
  insightsTeamSignalsQueryKeys,
} from "@/lib/insights-team-api";
import { previousComparablePeriod } from "@/lib/insights-views";
import { useAuthStore } from "@/store/auth";

const CURRENT_MONTH: InsightsPeriodParams = { period: "month", offset: 0 };

const PEOPLE = [
  { id: 11, name: "Ola K.", v: 96, r: 19, i: 9, p: 4, prev: 2, prec: 81 },
  { id: 12, name: "Kuba M.", v: 84, r: 16, i: 8, p: 3, prev: 3, prec: 77 },
  { id: 1, name: "Anna L.", v: 58, r: 11, i: 6, p: 2, prev: 1, prec: 64 },
  { id: 14, name: "Marta W.", v: 78, r: 14, i: 7, p: 2, prev: 3, prec: 72 },
  { id: 15, name: "Piotr S.", v: 58, r: 9, i: 4, p: 1, prev: 1, prec: 46 },
  { id: 16, name: "Ewa D.", v: 62, r: 8, i: 3, p: 1, prev: 2, prec: 44 },
  { id: 17, name: "Tomek R.", v: 48, r: 6, i: 2, p: 0, prev: 2, prec: 38 },
  { id: 18, name: "Bartek N.", v: 34, r: 7, i: 3, p: 1, prev: 1, prec: null },
];

function funnel(counts: Record<string, number>) {
  const stages = ["verified", "cv_sent", "interview", "hired"].map((stage) => ({
    stage,
    label: stage,
    count: counts[stage] ?? 0,
    mapped_from_traffit: true,
    share_pct: null,
  }));
  return {
    period: { kind: "month", start: "2026-09-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00", timezone: "Europe/Warsaw" },
    stages,
    conversions: [],
    coverage: { stage_moves_total: 0, stage_moves_manual: 0, manual_pct: null, unattributed_moves: 0, stages_not_mapped_from_traffit: [] },
  };
}

function leagueEntry(id: number, name: string, points: number, placements: number) {
  return { user_id: id, name, metric_value: points, role: "recruiter", placements, interviews: placements * 2, recommendations: placements * 4, verifications: placements * 20 };
}

function seeded(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnWindowFocus: false } },
  });
  const today = new Date();

  qc.setQueryData(insightsCampaignQueryKeys.active(), {
    id: 1, name: "Kampania Q3", emoji: "🎯", start_date: "2026-07-01", end_date: "2026-09-30",
    target_net: 70, is_active: true, created_at: "2026-06-20T09:00:00+02:00",
    window: { kind: "custom", start: "2026-07-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00", timezone: "Europe/Warsaw" },
    days_remaining: 6, has_started: true, placements: 68, resignations: 7, net: 61, progress_pct: 87,
    remaining_to_target: 9, placements_definition: "first_hired_per_candidate_job",
    placements_definition_note: "Placement = pierwsze wejście na etap „Zatrudniony”.",
    resignations_definition: "ended_engagement_by_effective_end_date_v2",
    resignations_definition_note: "Rezygnacja = kontrakt zakończony w oknie kampanii.",
    net_definition_note: "netto = placementy − rezygnacje",
  });

  const recruiterLeague = [
    leagueEntry(14, "Marta W.", 71, 9), leagueEntry(11, "Ola K.", 58, 7), leagueEntry(12, "Kuba M.", 44, 5),
    leagueEntry(15, "Piotr S.", 41, 5), leagueEntry(1, "Anna L.", 38, 4), leagueEntry(16, "Ewa D.", 31, 3),
    leagueEntry(18, "Bartek N.", 27, 3), leagueEntry(17, "Tomek R.", 19, 2), leagueEntry(19, "Iga Z.", 12, 1),
  ];
  qc.setQueryData(["insights", "champions", "quarterly_champions_recruiter"], {
    type: "quarterly_champions_recruiter", period: "2026-Q3", is_frozen: false, days_remaining: 6,
    top3: recruiterLeague.slice(0, 3).map((e, i) => ({ ...e, rank: i + 1, prize_pln: i === 0 ? 10000 : 0 })),
    // Numer miejsca niesie serwer (`award_ranked_rows`), jak w `/current`.
    full_ranking: recruiterLeague.map((e, i) => ({ ...e, rank: i + 1 })),
    requirement: "Minimum 2 placementy w kwartale.",
    points_formula: { placement: 5, interview: 2, recommendation: 1 },
    quarterly_prizes_pln: { "1": 10000, "2": 0, "3": 0 }, prize_pool_pln: null,
  });
  const dlLeague = [
    { user_id: 31, name: "Paweł G.", metric_value: 12, role: "delivery_lead", requests: 35 },
    { user_id: 32, name: "Kasia B.", metric_value: 9, role: "delivery_lead", requests: 31 },
    { user_id: 33, name: "Michał T.", metric_value: 7, role: "delivery_lead", requests: 32 },
    { user_id: 34, name: "Iza P.", metric_value: 4, role: "delivery_lead", requests: 12 },
  ];
  qc.setQueryData(["insights", "champions", "quarterly_champions_dl"], {
    type: "quarterly_champions_dl", period: "2026-Q3", is_frozen: false, days_remaining: 6,
    top3: dlLeague.slice(0, 3).map((e, i) => ({ ...e, rank: i + 1 })),
    full_ranking: dlLeague.map((e, i) => ({ ...e, rank: i + 1 })),
    requirement: null, points_formula: null, quarterly_prizes_pln: null, prize_pool_pln: null,
  });

  const placementsRanking = [
    { user_id: 11, name: "Ola K.", metric_value: 4, rank: 1, excluded: false, role: "recruiter" },
    { user_id: 12, name: "Kuba M.", metric_value: 3, rank: 2, excluded: false, role: "recruiter" },
    { user_id: 1, name: "Anna L.", metric_value: 2, rank: 3, excluded: false, role: "recruiter" },
    { user_id: 14, name: "Marta W.", metric_value: 2, rank: 4, excluded: true, role: "recruiter" },
  ];
  const recRanking = PEOPLE.slice(0, 6).map((p, i) => ({
    user_id: p.id, name: p.name, metric_value: p.r, rank: i + 1, excluded: p.id === 14,
    role: "recruiter", verifications: p.v, recommendations: p.r, precision_pct: p.prec,
    required_verifications: 64, qualified: p.v >= 64, workdays: 16, per_day: +(p.v / 16).toFixed(1),
    workdays_source: "calendar",
  }));
  const race = (ranking: unknown[]) => ({
    period: "2026-09", days_remaining: 6, prize: { amount_pln: 1500, name: "Nagroda 1 500 zł" },
    requirements: ["Lider kwartalny wykluczony z nagrody miesięcznej"], ranking,
    excluded_user_ids: [14], qualified_leader: ranking[0] ?? null, leader_tie_user_ids: [],
  });
  qc.setQueryData(["insights", "monthly-races", "current"], {
    recommendations: race(recRanking),
    placements: race(placementsRanking),
  });

  qc.setQueryData(["insights", "hall-of-fame", "all-time"], {
    type: "hall_of_fame", period: "all_time", top3: [],
    full_ranking: [
      { user_id: 11, name: "Ola K.", metric_value: 118, is_active: true },
      { user_id: 12, name: "Kuba M.", metric_value: 96, is_active: true },
      { user_id: 14, name: "Marta W.", metric_value: 81, is_active: true },
    ],
  });

  const seniorityEntry = (id: number, name: string, level: string, toNext: number | null, pct: number | null) => ({
    user_id: id, name, role: "recruiter", level, total_placements: 20, first_placement_month: "2024-03",
    placements_in_senior_window: 4, placements_in_expert_window: 4, placements_to_next_level: toNext,
    progress_pct: pct, senior_since: null, expert_since: null,
  });
  qc.setQueryData(["insights", "recruitment", "seniority"], {
    as_of: "2026-09-24",
    thresholds: { senior_placements: 6, senior_window_months: 6, expert_placements: 12, expert_window_months: 12, senior_alt_placements: 12, senior_alt_window_months: 12, expert_alt_placements: 24, expert_alt_window_months: 24 },
    window: { senior: { months: 6, start_month: "2026-04", end_month: "2026-09" }, expert: { months: 12, start_month: "2025-10", end_month: "2026-09" } },
    entries: [
      seniorityEntry(1, "Anna L.", "junior", 2, 67),
      seniorityEntry(15, "Piotr S.", "junior", 1, 83),
      seniorityEntry(16, "Ewa D.", "junior", 1, 83),
      seniorityEntry(12, "Kuba M.", "senior", 1, 92),
    ],
    totals: { users: 27, levels: { junior: 14, senior: 9, expert: 4 } },
    coverage: { unattributed_placements: 0, outside_pool_placements: 0, note: "" },
    regressions: null, journal: null,
  });

  // Mój miesiąc (Anna L., id 1).
  qc.setQueryData(["insights", "me", "panel"], {
    role: "recruiter", applies: true,
    weryfikacje: { day: 3, week: 14, month: 58 }, rekomendacje: { day: 0, week: 3, month: 11 },
    interview_month: 6, akceptacje_month: 3, placementy_month: 2, cv_to_base: null,
    precision: { value_pct: 64, verified: 58, sent: 37, target_pct: 75, window_days: 30 },
    target_verifications_daily: 4, target_placements_monthly: 1, target_cv_added_daily: null,
    target_precision_pct: 75,
  });
  qc.setQueryData(["insights", "me", "position", "quarterly_champions_recruiter"], {
    type: "quarterly_champions_recruiter", period: "2026-Q3", rank: 5,
    me: recruiterLeague[4], total: 9,
    context: recruiterLeague.slice(2, 7).map((e, i) => ({ ...e, rank: i + 3 })),
  });
  const monthFunnel = funnel({ verified: 412, cv_sent: 142, interview: 61, hired: 21 });
  qc.setQueryData(["insights", "recruitment", "funnel", CURRENT_MONTH], monthFunnel);
  qc.setQueryData(insightsTeamQueryKeys.teamTable(CURRENT_MONTH), {
    period: monthFunnel.period, columns: [],
    rows: PEOPLE.map((p) => ({ user_id: p.id, name: p.name, role: "recruiter", role_label: "Rekruter", is_active: true, verifications: p.v, recommendations: p.r, interviews: p.i, placements: p.p, total: p.v + p.r + p.i + p.p })),
    totals: { attributed: {}, unattributed: {}, all: {}, users: PEOPLE.length, former_employees: 0 },
  });

  // Zespół.
  qc.setQueryData(["insights", "recruitment", "funnel", ZESPOL_DEFAULT_PERIOD], monthFunnel);
  const previous = previousComparablePeriod(ZESPOL_DEFAULT_PERIOD, today);
  qc.setQueryData(
    ["insights", "recruitment", "funnel", previous?.params ?? null],
    funnel({ verified: 400, cv_sent: 156, interview: 60, hired: 17 }),
  );
  qc.setQueryData(insightsTeamSignalsQueryKeys.attention(), {
    items: [
      { kind: "stale_jobs", count: 9, label: "rekrutacji bez żadnego ruchu od 14 dni", report: "bez-ruchu" },
      { kind: "low_precision", count: 3, label: "osób z precyzją rekomendacji poniżej 50% (30 dni)", report: null, user_ids: [15, 16, 17] },
      { kind: "weak_preps", count: 4, label: "prepów ocenionych jako słabe w ostatnich 7 dniach", report: "prepy" },
    ],
  });
  qc.setQueryData(insightsTeamSignalsQueryKeys.people(ZESPOL_DEFAULT_PERIOD), {
    period: monthFunnel.period, workdays: 17, precision_target_pct: 75, low_precision_pct: 50,
    rows: PEOPLE.map((p) => ({ user_id: p.id, name: p.name, role: "recruiter", is_active: true, verifications: p.v, recommendations: p.r, interviews: p.i, placements: p.p, previous_placements: p.prev, verifications_per_workday: +(p.v / 17).toFixed(1), precision_pct: p.prec })),
    totals: { verifications: 518, recommendations: 90, interviews: 42, placements: 14, precision_pct: 63, people: 8, unattributed: 3 },
    previous_totals: { verifications: 500, recommendations: 95, interviews: 40, placements: 15 },
    outside_scope: { label: "Konta administracyjne", people: 1, verifications: 0, recommendations: 4, interviews: 2, placements: 5, previous_placements: 3 },
  });
  qc.setQueryData(performanceFlagsQueryKey, { flags_by_user: {}, types: [] });
  qc.setQueryData(insightsQueryKeys.dlPortfolio(ZESPOL_DL_PERIOD), {
    period: monthFunnel.period, hit_ratio_target_pct: 30, unattributed: { requests: 0, placements: 0 },
    leads: [
      { dl_id: 31, dl_name: "Paweł G.", is_active: true, requests: 35, vacancies: 40, placements: 12, hit_ratio: 34, fill_rate: 30, open_requests: 14, target_achieved: true, clients: [] },
      { dl_id: 32, dl_name: "Kasia B.", is_active: true, requests: 31, vacancies: 33, placements: 9, hit_ratio: 29, fill_rate: 27, open_requests: 11, target_achieved: false, clients: [] },
    ],
  });

  // Firma (liczby fikcyjne).
  qc.setQueryData(insightsQueryKeys.board(FIRMA_DEFAULT_PERIOD), {
    period: { kind: "quarter", start: "2026-07-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00", timezone: "Europe/Warsaw" },
    kpis: {
      placements_definition: "first_hired_per_candidate_job", placements: 61, verified: 1200, cv_sent: 420, interview: 180,
      funnel_efficiency_pct: 5, jobs_closed: 90, jobs_closed_with_placement: 15, hit_ratio_pct: 17, hit_ratio_definition: "",
      finance: { asof: "2026-09-24", basis: "", revenue_monthly_pln: 3410000, consultant_cost_monthly_pln: 2798000, margin_monthly_pln: 612000, margin_pct: 17.9, active_consultants: 318, active_contracts: 330, priced_contracts: 325, contracts_without_cost_leg: 0, complete: true },
    },
    trend: { months: [] },
    comparison: {
      previous_period: null, previous_asof: "2026-06-30",
      placements: { current: 61, previous: 55, delta: 6, change_pct: 10.9 },
      revenue_monthly_pln: { current: 3410000, previous: 3280000, delta: 130000, change_pct: 4 },
      margin_monthly_pln: { current: 612000, previous: 600000, delta: 12000, change_pct: 2 },
      active_consultants: { current: 318, previous: 307, delta: 11, change_pct: 3.6 },
      complete: true,
    },
    degraded: null,
  });
  const clients = [
    ["Klient A", 110000], ["Klient B", 80000], ["Klient C", 61000], ["Klient D", 49000], ["Klient E", 43000],
    ["Klient F", 37000], ["Klient G", 31000], ["Klient H", 24000], ["Klient I", 90000], ["Klient J", 87000],
  ] as const;
  qc.setQueryData(insightsQueryKeys.clientsRanking(FIRMA_DEFAULT_PERIOD), {
    period: { kind: "quarter", start: "2026-07-01T00:00:00+02:00", end: "2026-10-01T00:00:00+02:00", timezone: "Europe/Warsaw" },
    valuation: { on: "2026-09-24", basis: "", note: "" },
    totals: {},
    clients: clients.map(([name, margin], i) => ({ client_id: i + 1, name, monthly_margin_total: margin, margin_complete: true })),
  });
  const series2025 = [15, 17, 19, 16, 18, 14, 12, 15, 19, 21, 18, 11];
  const series2026 = [18, 20, 22, 19, 24, 21, 17, 23, 21, null, null, null];
  qc.setQueryData(insightsQueryKeys.boardYoY({ years: 2 }), {
    years: [2025, 2026], asof: "2026-09-24",
    coverage: { contracts_by_year: {}, money_comparable_across_years: false, message: null },
    partial_month: { year: 2026, month: 9 }, month_labels: [],
    metrics: [
      { key: "placements", group: "hr", label: "Liczba placementów", unit: "count", aggregate: "sum", components: null, yearly: null, lower_is_better: false, definition: null, note: null, basis: "pipeline", series: { "2025": series2025, "2026": series2026 } },
      { key: "hit_ratio_pct", group: "operacyjne", label: "Hit ratio", unit: "pct", aggregate: "ratio", components: { numerator: "closed_jobs_filled", denominator: "closed_jobs_total" }, yearly: null, lower_is_better: false, definition: null, note: null, basis: "pipeline", series: { "2025": [12, 15, 14, 16, 13, 15, 17, 14, 16, 15, 14, 13], "2026": [16, 18, 17, 19, 16, 18, 20, 17, 18, null, null, null] } },
    ],
    component_series: {
      closed_jobs_filled: { "2025": [12, 15, 14, 16, 13, 15, 17, 14, 16, 15, 14, 13], "2026": [16, 18, 17, 19, 16, 18, 20, 17, 18, null, null, null] },
      closed_jobs_total: { "2025": Array(12).fill(100), "2026": [100, 100, 100, 100, 100, 100, 100, 100, 100, null, null, null] },
    },
    placements_by_client: {}, degraded: null,
  });
  return qc;
}

const ROLES = {
  recruiter: { role: "recruiter", roles: ["recruiter"], capabilities: [] },
  hor: { role: "head_of_recruitment", roles: ["head_of_recruitment"], capabilities: ["view_team_kpi"] },
  admin: { role: "admin", roles: ["admin"], capabilities: ["view_team_kpi", "view_finance"] },
} as const;

const VIEWS = ["rywalizacja", "moj-miesiac", "zespol", "firma", "raporty"] as const;

function Harness() {
  const params = useSearchParams();
  const as = (params.get("as") ?? "recruiter") as keyof typeof ROLES;
  const view = (VIEWS as readonly string[]).includes(params.get("view") ?? "")
    ? (params.get("view") as (typeof VIEWS)[number])
    : "rywalizacja";
  const report = params.get("report");
  const [client] = useState(seeded);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const persona = ROLES[as] ?? ROLES.recruiter;
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Anna L.",
        role: persona.role,
        roles: persona.roles,
        capabilities: persona.capabilities,
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      hydrated: true,
    });
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, [as]);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <ToastProvider>
      <QueryClientProvider client={client}>
        <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
          <nav aria-label="Podgląd — widoki" className="flex flex-wrap gap-2 text-xs">
            {VIEWS.map((v) => (
              <a
                key={v}
                href={`/preview/insights?as=${as}&view=${v}`}
                className={v === view ? "font-semibold text-primary" : "text-muted-foreground"}
              >
                {v}
              </a>
            ))}
            <span className="text-muted-foreground">· rola: {as}</span>
          </nav>
          {view === "rywalizacja" && <RywalizacjaView />}
          {view === "moj-miesiac" && <MojMiesiacView />}
          {view === "zespol" && <ZespolView />}
          {view === "firma" && <FirmaView />}
          {view === "raporty" && (
            <RaportyView reportId={isReportId(report) ? report : null} />
          )}
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}

export default function InsightsPreview() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
