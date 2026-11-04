"use client";

// Publiczny harness nowego Insights (24.09.2026): pięć widoków na danych
// FIKCYJNYCH, ZERO zapytań — każdy klucz jest zasiany, a interceptor odcina
// sieć (pilnuje `harness-seeds.test.ts`). Widoki renderowane wprost, nie przez
// `InsightsView`: ten przepisuje adres na `/insights`, czyli wyszedłby
// z podglądu. Zmiana okresu w podglądzie prowadzi na `/insights` — nie klikaj.
//
// `?as=recruiter|hor|admin|board|dl` wybiera rolę, `?view=` widok, `?report=` raport.
// Na „Rywalizacji” zasiane są dwa okresy: trwający (źródło mieszane) i Q3 2026
// / wrzesień 2026 jako rozliczone z DynaReportera — inne okresy z listy wyboru
// pokażą błąd pobierania, bo sieć jest odcięta.

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
import { DL_SEND_QUEUE_QUERY_KEY } from "@/lib/api/boardTasks";
import { payrollKeys } from "@/lib/api/hr-payroll";
import { insightsQueryKeys, type InsightsPeriodParams } from "@/lib/insights-api";
import { performanceFlagsQueryKey } from "@/lib/insights-flags-api";
import { isReportId } from "@/lib/insights-reports";
import {
  insightsTeamQueryKeys,
  insightsTeamSignalsQueryKeys,
} from "@/lib/insights-team-api";
import { currentMonthKey, currentQuarterKey } from "@/lib/insights-races-api";
import { previousComparablePeriod } from "@/lib/insights-views";
import { useAuthStore } from "@/store/auth";
import { whoCountsQueryKey } from "@/components/v2/kpi/WhoCountsList";
import { myWhoCountsQuery } from "@/components/insights/sections/WhoCountsPanel";
import { warsawToday } from "@/lib/kpi-who-counts";
import type {
  RecruitmentActivityDetailResponse,
  RecruitmentActivityState,
} from "@/lib/recruitment-activity-api";

const CURRENT_MONTH: InsightsPeriodParams = { period: "month", offset: 0 };

const PEOPLE = [
  { id: 11, name: "Ola K.", v: 96, r: 19, i: 9, a: 5, p: 4, prev: 2, prec: 81, t: 2, f: 14 },
  { id: 12, name: "Kuba M.", v: 84, r: 16, i: 8, a: 3, p: 3, prev: 3, prec: 77, t: 2, f: 11 },
  { id: 1, name: "Anna L.", v: 58, r: 11, i: 6, a: 3, p: 2, prev: 1, prec: 64, t: 1, f: 11 },
  { id: 14, name: "Marta W.", v: 78, r: 14, i: 7, a: 3, p: 2, prev: 3, prec: 72, t: 2, f: 9 },
  { id: 15, name: "Piotr S.", v: 58, r: 9, i: 4, a: 1, p: 1, prev: 1, prec: 46, t: 2, f: 6 },
  { id: 16, name: "Ewa D.", v: 62, r: 8, i: 3, a: 1, p: 1, prev: 2, prec: 44, t: 1, f: 5 },
  { id: 17, name: "Tomek R.", v: 48, r: 6, i: 2, a: 0, p: 0, prev: 2, prec: 38, t: 1, f: 3 },
  { id: 18, name: "Bartek N.", v: 34, r: 7, i: 3, a: 1, p: 1, prev: 1, prec: null, t: 1, f: 4 },
];
// Konto wyłączone — w „Zespół → Ludzie” trafia do wiersza „Byli pracownicy”.
const FORMER_PEOPLE = [{ id: 19, name: "Monika B.", v: 12, r: 5, i: 2, a: 0, p: 1, prev: 2, prec: 70, t: 0, f: 0 }];

function funnel(counts: Record<string, number>, countedFrom: Record<string, string> = {}) {
  const stages = ["verified", "cv_sent", "client_interview", "acceptance", "hired"].map((stage) => ({
    stage,
    label: stage,
    count: counts[stage] ?? 0,
    mapped_from_traffit: stage !== "acceptance",
    share_pct: null,
    counted_from: countedFrom[stage] ?? null,
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

function whoCountsSeed(today: string): RecruitmentActivityDetailResponse {
  const person = (id: number, name: string, role = "recruiter") => ({ id, name, role });
  const at = `${today}T08:30:00Z`;
  const item = (
    id: number,
    name: string,
    jobId: number,
    title: string,
    client: string,
    mover: ReturnType<typeof person>,
    state: RecruitmentActivityState,
  ) => ({
    candidate: { id, name, href: `/candidates/${id}` },
    job: { id: jobId, title, working_title: title, client_reference: null, client_name: client, href: `/jobs/${jobId}?candidate=${id}` },
    credited_user: person(1, "Anna L."),
    reached_at: at,
    moved_by: mover,
    state,
    state_stage: state === "at_client" ? "client_interview" : "cv_sent",
    state_since: at,
    candidate_jobs: 1,
  });
  const lead = person(31, "Paweł G.", "delivery_lead");
  return {
    generated_at: at,
    metric: "recommendation",
    window: "week",
    page: 1,
    page_size: 50,
    total: 3,
    period_total: 3,
    scope: "person",
    subject: person(1, "Anna L."),
    people: 3,
    moved_by_credited: 1,
    states: { waiting: 2, at_client: 1 },
    items: [
      item(501, "Kamil Wzorcowy", 901, "Senior Java Developer", "Bank Przykładowy", lead, "waiting"),
      item(502, "Ewa Fikcyjna", 902, "Analityk biznesowy", "Ubezpieczenia Wzorcowe", person(1, "Anna L."), "at_client"),
      item(503, "Marek Próbny", 903, "DevOps Engineer", "Telekom Testowy", lead, "waiting"),
    ],
  };
}

let dlGoalsSeed: unknown = null;

function seeded(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnWindowFocus: false } },
  });
  const today = new Date();

  const recruiterLeague = [
    leagueEntry(14, "Marta W.", 71, 9), leagueEntry(11, "Ola K.", 58, 7), leagueEntry(12, "Kuba M.", 44, 5),
    leagueEntry(15, "Piotr S.", 41, 5), leagueEntry(1, "Anna L.", 38, 4), leagueEntry(16, "Ewa D.", 31, 3),
    leagueEntry(18, "Bartek N.", 27, 3), leagueEntry(17, "Tomek R.", 19, 2), leagueEntry(19, "Iga Z.", 12, 1),
  ];
  // Trwający kwartał: część liczb z DynaReportera, reszta z NEXUS-a (zdanie fikcyjne).
  const mixed = {
    is_frozen: false, closure_status: null, source: "mixed",
    source_note: "Część okresu z poprzedniego systemu, reszta z NEXUS-a.",
  };
  const settled = {
    is_frozen: true, days_remaining: null, source: "dynareporter",
    source_note: "Wynik z poprzedniego systemu — rozliczony przy przejściu na NEXUS.",
  };
  const recruiterCurrent = {
    type: "quarterly_champions_recruiter", period: currentQuarterKey(), days_remaining: 6, ...mixed,
    top3: recruiterLeague.slice(0, 3).map((e, i) => ({ ...e, rank: i + 1, prize_pln: i === 0 ? 10000 : 0 })),
    // Numer miejsca niesie serwer (`award_ranked_rows`), jak w `/current`.
    full_ranking: recruiterLeague.map((e, i) => ({ ...e, rank: i + 1 })),
    requirement: "Minimum 2 placementy w kwartale.",
    points_formula: { placement: 5, interview: 2, recommendation: 1 },
    quarterly_prizes_pln: { "1": 10000, "2": 0, "3": 0 }, prize_pool_pln: null,
  };
  qc.setQueryData(["insights", "champions", "quarterly_champions_recruiter", "current"], recruiterCurrent);
  // Q3 2026 rozliczony z DynaReportera — podium zamrożone.
  qc.setQueryData(["insights", "champions", "quarterly_champions_recruiter", "Q3 2026"], {
    ...recruiterCurrent, period: "Q3 2026", ...settled, closure_status: "frozen",
  });
  // Liga DL od Q4 2026: kolejność po hit ratio (placementy ÷ zamknięte), bez nagród.
  const dlLeague = [
    { user_id: 34, name: "Iza P.", metric_value: 4, hit_ratio: 33.3, role: "delivery_lead", requests: 12 },
    { user_id: 31, name: "Paweł G.", metric_value: 12, hit_ratio: 34.3, role: "delivery_lead", requests: 35 },
    { user_id: 32, name: "Kasia B.", metric_value: 9, hit_ratio: 29, role: "delivery_lead", requests: 31 },
    { user_id: 33, name: "Michał T.", metric_value: 7, hit_ratio: 21.9, role: "delivery_lead", requests: 32 },
  ].sort((a, b) => b.hit_ratio - a.hit_ratio);
  const dlUnplaced = {
    user_id: 35, name: "Ola S.", metric_value: 2, hit_ratio: 50, role: "delivery_lead", requests: 4,
    qualified: false, disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET", "MIN_CLOSED_REQUESTS_NOT_MET"],
    required_placements: 3, required_closed_requests: 5,
  };
  // Liga DL liczy tylko NEXUS — DynaReporter jej nie prowadził, więc bez paska źródła.
  const nexusOnly = { is_frozen: false, closure_status: null, source: "nexus", source_note: null };
  const dlCurrent = {
    type: "quarterly_champions_dl", period: currentQuarterKey(), days_remaining: 6, ...nexusOnly,
    top3: dlLeague.slice(0, 3).map((e, i) => ({ ...e, rank: i + 1, prize_pln: 0 })),
    full_ranking: [
      ...dlLeague.map((e, i) => ({ ...e, rank: i + 1, prize_pln: 0 })),
      { ...dlUnplaced, rank: null, prize_pln: null },
    ],
    requirement:
      "Miejsce w klasyfikacji: minimum 3 placementy i 5 zamkniętych rekrutacji w kwartale. Liga DL nie ma nagród.",
    points_formula: null, quarterly_prizes_pln: null, prize_pool_pln: null,
  };
  qc.setQueryData(["insights", "champions", "quarterly_champions_dl", "current"], dlCurrent);
  // Q3 2026 w lidze DL: nikt nie spełnił warunku — okres bez zwycięzcy.
  qc.setQueryData(["insights", "champions", "quarterly_champions_dl", "Q3 2026"], {
    ...dlCurrent, period: "Q3 2026", is_frozen: true, days_remaining: null,
    closure_status: "no_winner", top3: [],
    full_ranking: dlLeague.map((e) => ({ ...e, rank: null, qualified: false, disqualification_reasons: ["MIN_PLACEMENTS_NOT_MET"] })),
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
    period: currentMonthKey(), days_remaining: 6, prize: { amount_pln: 1500, name: "Nagroda 1 500 zł" },
    requirements: ["Lider kwartalny wykluczony z nagrody miesięcznej"], ranking,
    excluded_user_ids: [14], qualified_leader: ranking[0] ?? null, leader_tie_user_ids: [], ...mixed,
  });
  qc.setQueryData(["insights", "monthly-races", "current"], {
    recommendations: race(recRanking),
    placements: race(placementsRanking),
  });
  // Wrzesień 2026 rozliczony z DynaReportera: mianownik „/dzień” to dni
  // przepracowane stamtąd, a w Wyścigu Placementów remis czeka na admina.
  qc.setQueryData(["insights", "monthly-races", "2026-09"], {
    recommendations: {
      ...race(recRanking.map((e) => ({ ...e, workdays_source: "dynareporter" }))),
      period: "2026-09", ...settled, closure_status: "frozen",
    },
    placements: {
      ...race(placementsRanking.map((e) => (e.user_id === 12 ? { ...e, metric_value: 4 } : e))),
      period: "2026-09", ...settled,
      closure_status: "tie_pending", qualified_leader: null, leader_tie_user_ids: [11, 12],
    },
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

  // „Zamknięcia i hit ratio” (21.10.2026) — `?as=hor&view=raporty&report=zamkniecia-hit-ratio`.
  const closureRow = {
    client_name: "Bank Przykładowy S.A.",
    duplicate_of_job_id: null,
    delivery_lead_name: "Olga Wzorcowa",
  };
  qc.setQueryData(insightsQueryKeys.hitRatioClosures(), {
    since: "2026-10-11T22:00:00+00:00",
    counts: { won: 6, lost: 9, neutral: 3, unreviewed: 2 },
    hit_ratio: 35.3,
    neutral: [
      { ...closureRow, job_id: 9101, title: "Programista Java", close_reason: "duplicate", close_notes: "Ten sam request założony drugi raz z maila klienta.", closed_at: "2026-10-20T10:00:00+00:00", closed_by_name: "Olga Wzorcowa" },
      { ...closureRow, job_id: 9102, title: "Analityk biznesowy", close_reason: "internal_hire", close_notes: "Klient przesunął osobę z innego zespołu.", closed_at: "2026-10-16T09:00:00+00:00", closed_by_name: "Olga Wzorcowa" },
      { ...closureRow, job_id: 9103, title: "Tester automatyzujący", close_reason: "paused", close_notes: "Klient wraca w styczniu.", closed_at: "2026-10-14T12:00:00+00:00", closed_by_name: "Karol Wzorcowy" },
    ],
    unreviewed: [
      { ...closureRow, job_id: 9104, title: "DevOps Engineer", close_reason: "other", close_notes: null, closed_at: "2026-10-13T08:00:00+00:00", closed_by_name: "Karol Wzorcowy" },
      { ...closureRow, job_id: 9105, title: "Architekt chmury", close_reason: null, close_notes: null, closed_at: "2026-10-12T15:00:00+00:00", closed_by_name: null },
    ],
  });

  // Mój miesiąc (Anna L., id 1).
  qc.setQueryData(["insights", "me", "panel"], {
    role: "recruiter", applies: true,
    weryfikacje: { day: 3, week: 14, month: 58 }, rekomendacje: { day: 0, week: 3, month: 11 },
    interview_month: 6, akceptacje_month: 3, placementy_month: 2, cv_to_base: null,
    precision: { value_pct: 64, verified: 58, sent: 37, target_pct: 75, window_days: 30 },
    target_verifications_daily: 4, target_placements_monthly: 1,
    target_precision_pct: 75,
  });
  qc.setQueryData(["insights", "me", "position", "quarterly_champions_recruiter"], {
    type: "quarterly_champions_recruiter", period: "2026-Q3", rank: 5,
    me: recruiterLeague[4], total: 9,
    context: recruiterLeague.slice(2, 7).map((e, i) => ({ ...e, rank: i + 3 })),
  });
  // Cele z górnego paska i „w drodze” (22.10.2026).
  const kpi = (
    kpi_id: string,
    period: "day" | "week" | "month",
    title_pl: string,
    short_title_pl: string,
    target: number,
    current: number,
    state: "on_track" | "behind" | "hit",
    expected_count: number,
  ) => ({
    kpi_id, period, title_pl, short_title_pl, target, current, state, expected_count,
    description_pl: "", progress_pct: (100 * current) / target, deadline_hours_left: 6,
  });
  qc.setQueryData(["kpis", "me", "today"], [
    kpi("daily_first_verifications", "day", "Weryfikacje dziś", "Weryfikacje", 4, 3, "on_track", 2.4),
    kpi("weekly_cvs_sent", "week", "Rekomendacje w tygodniu", "Rekomendacje", 5, 2, "behind", 4),
    kpi("monthly_placements", "month", "Placementy w tym miesiącu", "Placementy", 1, 2, "hit", 0.7),
  ]);
  // Cele DL tylko dla persony DL (efekt w `Harness`) — w aplikacji rekruter
  // nigdy ich nie pobiera, a zasiana odpowiedź pokazałaby mu cudze cele.
  dlGoalsSeed = {
    kind: "delivery_lead", scope_label: "Q4 2026", people: null, closed_requests: 29,
    goals: [
      { goal_id: "dl_hit_ratio_quarter", title_pl: "Hit ratio portfela w kwartale", short_title_pl: "Hit ratio", period: "quarter", unit: "pct", target: 30, current: 31, progress_pct: null, state: "hit", note: null },
      { goal_id: "dl_placements_quarter", title_pl: "Placementy portfela w kwartale", short_title_pl: "Placementy", period: "quarter", unit: "count", target: 9, current: 9, progress_pct: null, state: "hit", note: "Rekrutacje zamknięte w kwartale: 29" },
    ],
  };
  const flightCols = (cv_qc: number, cv_sent: number, interview: number, contract: number) => [
    { column: "cv_qc", label: "Czekają na wysyłkę CV", count: cv_qc, stale_count: 0, oldest_days: cv_qc ? 2 : null },
    { column: "cv_sent", label: "Czekają na decyzję klienta", count: cv_sent, stale_count: Math.min(3, cv_sent), oldest_days: cv_sent ? 16 : null },
    { column: "client_interview", label: "Rozmowy u klienta", count: interview, stale_count: 0, oldest_days: interview ? 4 : null },
    { column: "contract", label: "Akceptacje do domknięcia", count: contract, stale_count: contract ? 1 : 0, oldest_days: contract ? 11 : null },
  ];
  const flightForecast = { hired: 12, resolved: 14, min_sample: 10, since: "2026-10-12", rate_pct: 85.7 };
  const person = (candidate_id: number, candidate_name: string, job_id: number, job_title: string, client_name: string, column: string, stage_label: string, days: number) => ({
    candidate_id, candidate_name, job_id, job_title, client_id: 1, client_name, delivery_lead_name: "Paweł G.",
    column, stage_key: column, stage_label, since: "2026-10-12", days,
  });
  qc.setQueryData(insightsQueryKeys.inFlightMe("mine"), {
    asof: "2026-10-22", stale_days: 10, columns: flightCols(0, 7, 2, 2), acceptances: null,
    people: [
      person(501, "Marek Próbny", 9201, "DevOps Engineer", "Telekom Testowy", "contract", "Umowa wysłana", 11),
      person(502, "Kamil Wzorcowy", 9202, "Senior Java Developer", "Bank Przykładowy", "contract", "Akceptacja", 3),
      person(503, "Ewa Fikcyjna", 9203, "Analityk biznesowy", "Ubezpieczenia Wzorcowe", "client_interview", "Rozmowa u klienta", 2),
      person(504, "Jan Przykładowy", 9204, "Tester automatyzujący", "Bank Przykładowy", "client_interview", "Prep", 1),
      person(505, "Ola Testowa", 9205, "Project Manager", "Energetyka Próbna", "cv_sent", "Wysłane do klienta", 16),
      person(506, "Piotr Wzór", 9201, "DevOps Engineer", "Telekom Testowy", "cv_sent", "Wysłane do klienta", 4),
    ],
    forecast: { open: 2, low: 1, high: 2, ...flightForecast },
    definitions: { columns: "", forecast: "" },
  });
  qc.setQueryData(insightsQueryKeys.inFlightMe("portfolio"), {
    asof: "2026-10-22", stale_days: 10, columns: flightCols(3, 18, 5, 4), acceptances: null,
    people: [
      person(511, "Marek Próbny", 9201, "DevOps Engineer", "Telekom Testowy", "contract", "Umowa wysłana", 19),
      person(512, "Kamil Wzorcowy", 9202, "Senior Java Developer", "Bank Przykładowy", "contract", "Akceptacja", 3),
      person(513, "Ewa Fikcyjna", 9203, "Analityk biznesowy", "Ubezpieczenia Wzorcowe", "client_interview", "Rozmowa u klienta", 2),
    ],
    forecast: { open: 4, low: 3, high: 4, ...flightForecast },
    definitions: { columns: "", forecast: "" },
  });
  qc.setQueryData(payrollKeys.me, {
    current_rate: null, rates: [], business_days_required: 21,
    bonuses: [
      { id: 1, recipient_user_id: 1, recipient_name: "Anna L.", proposed_by: null, proposed_by_name: null, amount: "1500.00", currency: "PLN", category: "placement", category_label: "Placement", period_year: 2026, period_month: 10, status: "assigned", source: "contract_placement", contract_id: 77, eligible_on: "2026-10-20", eligible: true, description: "Premia rekrutera — placement: Jan Przykładowy (Bank Przykładowy)", assigned_by: null, assigned_at: "2026-10-20T08:00:00Z", cancelled_at: null },
    ],
    forecast: [
      { key: "f1", contract_id: 78, role: "recruiter", category: "placement", category_label: "Placement", description: "Premia rekrutera — placement: Ewa Fikcyjna (Ubezpieczenia Wzorcowe)", amount: "1500.00", currency: "PLN", amount_missing_reason: null, start_date: "2026-11-03", started: false, eligible_on: "2026-12-02", business_days_elapsed: 0, business_days_required: 21 },
    ],
  });
  qc.setQueryData(DL_SEND_QUEUE_QUERY_KEY, { ready: [], ready_total: 3, not_ready_total: 2, imported_total: 0, worst_urgency: null });
  qc.setQueryData(["insights", "me", "position", "quarterly_champions_dl"], {
    type: "quarterly_champions_dl", period: "2026-Q4", rank: 2, total: 5,
    me: { user_id: 1, name: "Anna L.", metric_value: 9, rank: 2 }, context: [],
  });
  qc.setQueryData(insightsQueryKeys.dlPortfolio({ period: "quarter", offset: 0 }), {
    period: { kind: "quarter", start: "2026-10-01T00:00:00+02:00", end: "2027-01-01T00:00:00+01:00", timezone: "Europe/Warsaw" },
    hit_ratio_target_pct: 30, unattributed: { requests: 0, placements: 0 },
    leads: [{
      dl_id: 1, dl_name: "Anna L.", is_active: true, requests: 29, vacancies: 33, placements: 9, hit_ratio: 31, fill_rate: 27, open_requests: 15, target_achieved: true,
      clients: [
        { client_id: 1, client_name: "Bank Przykładowy", requests: 11, vacancies: 12, placements: 4, hit_ratio: 36, fill_rate: 33, open_jobs: 6, monthly_placements: [], top_hiring_manager: null },
        { client_id: 2, client_name: "Ubezpieczenia Wzorcowe", requests: 9, vacancies: 10, placements: 3, hit_ratio: 33, fill_rate: 30, open_jobs: 4, monthly_placements: [], top_hiring_manager: null },
        { client_id: 3, client_name: "Telekom Testowy", requests: 6, vacancies: 8, placements: 1, hit_ratio: 17, fill_rate: 12, open_jobs: 3, monthly_placements: [], top_hiring_manager: null },
      ],
    }],
  });
  const monthFunnel = funnel(
    { verified: 412, cv_sent: 142, client_interview: 61, acceptance: 25, hired: 21 },
    { acceptance: "2026-10-12" },
  );
  // Zespół v3 (22.10.2026): cele zespołu, „w drodze” firmy, trend tygodni.
  qc.setQueryData(insightsQueryKeys.teamGoals(), {
    kind: "team", scope_label: "Zespół rekrutacji", people: 9,
    goals: [
      { goal_id: "team_daily_first_verifications", title_pl: "Weryfikacje zespołu dziś", short_title_pl: "Weryfikacje", period: "day", unit: "count", target: 36, current: 27, progress_pct: 75, state: "on_track", note: null, expected: 22 },
      { goal_id: "team_weekly_cvs_sent", title_pl: "Rekomendacje zespołu w tygodniu", short_title_pl: "Rekomendacje", period: "week", unit: "count", target: 45, current: 24, progress_pct: 53, state: "behind", note: null, expected: 36 },
      { goal_id: "team_monthly_placements", title_pl: "Placementy zespołu w miesiącu", short_title_pl: "Placementy", period: "month", unit: "count", target: 25, current: 16, progress_pct: 64, state: "behind", note: "Suma celów osób z tym celem: 9", expected: 18 },
    ],
    company_month_placements: 21,
  });
  qc.setQueryData(insightsQueryKeys.inFlight(), {
    asof: "2026-10-22", stale_days: 10, columns: flightCols(38, 64, 23, 10),
    acceptances: [
      { job_id: 9201, job_title: "DevOps Engineer", client_id: 3, client_name: "Telekom Testowy", delivery_lead_name: "Paweł G.", stage_key: "contract_sent", stage_label: "Umowa wysłana", since: "2026-10-03", days: 19 },
      { job_id: 9202, job_title: "Senior Java Developer", client_id: 1, client_name: "Bank Przykładowy", delivery_lead_name: "Kasia B.", stage_key: "acceptance", stage_label: "Akceptacja", since: "2026-10-07", days: 15 },
      { job_id: 9203, job_title: "Analityk biznesowy", client_id: 2, client_name: "Ubezpieczenia Wzorcowe", delivery_lead_name: "Paweł G.", stage_key: "acceptance", stage_label: "Akceptacja", since: "2026-10-19", days: 3 },
    ],
    forecast: { open: 10, low: 8, high: 9, ...flightForecast },
    definitions: { columns: "", forecast: "" },
  });
  const trendWeek = (week_start: string, v: number, r: number, i: number, a: number | null, p: number, partial = false) => ({
    week_start, partial, counts: { verified: v, cv_sent: r, client_interview: i, acceptance: a, hired: p },
  });
  qc.setQueryData(insightsQueryKeys.weeklyTrend(8), {
    weeks: [
      trendWeek("2026-08-31", 88, 34, 12, null, 4), trendWeek("2026-09-07", 95, 31, 14, null, 5),
      trendWeek("2026-09-14", 91, 36, 13, null, 6), trendWeek("2026-09-21", 104, 29, 11, null, 5),
      trendWeek("2026-09-28", 99, 27, 12, null, 7), trendWeek("2026-10-05", 110, 25, 15, null, 6),
      trendWeek("2026-10-12", 118, 26, 14, 9, 7), trendWeek("2026-10-19", 72, 15, 9, 6, 3, true),
    ],
  });
  qc.setQueryData(["insights", "recruitment", "funnel", CURRENT_MONTH], monthFunnel);
  const monthTeamTable = {
    period: monthFunnel.period, columns: [],
    rows: PEOPLE.map((p) => ({ user_id: p.id, name: p.name, role: "recruiter", role_label: "Rekruter", is_active: true, verifications: p.v, recommendations: p.r, interviews: p.i, placements: p.p, total: p.v + p.r + p.i + p.p })),
    totals: { attributed: {}, unattributed: {}, all: {}, users: PEOPLE.length, former_employees: 0 },
  };
  qc.setQueryData(insightsTeamQueryKeys.teamTable(CURRENT_MONTH), monthTeamTable);
  // „Mój miesiąc” czyta tabelę ze średnią verifier-anchored (runda 6 audytu).
  qc.setQueryData(insightsTeamQueryKeys.teamTableAnchored(CURRENT_MONTH), {
    ...monthTeamTable,
    anchored_average: { attribution: "verifier_anchored", people: PEOPLE.length, recommendations: 11.4 },
  });

  // Zespół.
  qc.setQueryData(["insights", "recruitment", "funnel", ZESPOL_DEFAULT_PERIOD], monthFunnel);
  const previous = previousComparablePeriod(ZESPOL_DEFAULT_PERIOD, today);
  qc.setQueryData(
    ["insights", "recruitment", "funnel", previous?.params ?? null],
    funnel({ verified: 400, cv_sent: 156, client_interview: 60, hired: 17 }),
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
    rows: [...PEOPLE.map((p) => ({ ...p, active: true })), ...FORMER_PEOPLE.map((p) => ({ ...p, active: false }))].map((p) => ({ user_id: p.id, name: p.name, role: "recruiter", is_active: p.active, verifications: p.v, recommendations: p.r, interviews: p.i, acceptances: p.a, placements: p.p, placements_target: p.t || null, in_flight: p.f, previous_placements: p.prev, verifications_per_workday: +(p.v / 17).toFixed(1), precision_pct: p.prec })),
    totals: { verifications: 518, recommendations: 90, interviews: 42, placements: 14, precision_pct: 63, people: 8, unattributed: 3 },
    previous_totals: { verifications: 500, recommendations: 95, interviews: 40, placements: 15 },
    outside_scope: { label: "Konta administracyjne", people: 1, verifications: 0, recommendations: 4, interviews: 2, placements: 5, previous_placements: 3 },
  });
  qc.setQueryData(performanceFlagsQueryKey, { flags_by_user: {}, types: [] });
  // „Kto się liczy do celów” w Mój miesiąc (17.10.2026): rekomendacje osoby 1
  // w bieżącym tygodniu — ten sam klucz co `MyWhoCountsPanel` po wejściu.
  const whoToday = warsawToday();
  qc.setQueryData(
    whoCountsQueryKey("1:none", "recommendation", myWhoCountsQuery("week", whoToday, 1), null, 1, 50),
    whoCountsSeed(whoToday),
  );
  qc.setQueryData(insightsQueryKeys.dlPortfolio(ZESPOL_DL_PERIOD), {
    period: monthFunnel.period, hit_ratio_target_pct: 30, unattributed: { requests: 0, placements: 0 },
    leads: [
      { dl_id: 31, dl_name: "Paweł G.", is_active: true, requests: 35, vacancies: 40, placements: 12, hit_ratio: 34, fill_rate: 30, open_requests: 14, target_achieved: true, clients: [] },
      { dl_id: 32, dl_name: "Kasia B.", is_active: true, requests: 31, vacancies: 33, placements: 9, hit_ratio: 29, fill_rate: 27, open_requests: 11, target_achieved: false, clients: [] },
      { dl_id: 35, dl_name: "Diana K.", is_active: false, requests: 18, vacancies: 20, placements: 4, hit_ratio: 22, fill_rate: 20, open_requests: 0, target_achieved: false, clients: [] },
    ],
  });

  // Firma (liczby fikcyjne).
  // Firma v3 (22.10.2026): ruch konsultantów, lejek kwartału.
  qc.setQueryData(insightsQueryKeys.boardFlows(FIRMA_DEFAULT_PERIOD), {
    period: monthFunnel.period,
    window: { from: "2026-10-01", to: "2026-10-22" },
    previous_window: { from: "2026-07-01", to: "2026-07-22" },
    consultants: { starts: 22, ends: 9, resignations: 4, net: 13 },
    previous_consultants: { starts: 17, ends: 9, resignations: 3, net: 8 },
    ending_without_continuation: { days: 30, contracts: 7 },
    jobs: { open: 84, open_clients: 31, new: 41, previous_new: 35 },
  });
  qc.setQueryData(
    ["insights", "recruitment", "funnel", FIRMA_DEFAULT_PERIOD],
    funnel(
      { verified: 486, cv_sent: 171, client_interview: 72, acceptance: 27, hired: 22 },
      { acceptance: "2026-10-12" },
    ),
  );
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
  // Rada nadzorcza (0490): Firma z kwotami rolą, zespół imiennie, bez „Mój miesiąc”.
  board: { role: "board", roles: ["board"], capabilities: ["view_team_kpi"] },
  // Delivery Lead (22.10.2026): „Mój miesiąc” = portfel, cele DL.
  dl: { role: "delivery_lead", roles: ["delivery_lead"], capabilities: ["view_team_kpi"] },
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
    if (as === "dl") {
      client.setQueryData(["kpis", "me", "goals"], dlGoalsSeed);
      client.setQueryData(["kpis", "me", "today"], []);
    }
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, [as, client]);

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
