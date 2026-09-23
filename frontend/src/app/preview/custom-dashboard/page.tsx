"use client";

// Publiczny harness własnego pulpitu (0337): pusty start i pulpit z kafelkami.
// ZERO zapytań — każdy klucz jest zasiany, a interceptor odcina sieć, więc
// strona nie przerzuca na /login (pilnuje `harness-seeds.test.ts`).
// Zapis układu w podglądzie kończy się komunikatem o błędzie — to zamierzone.

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CustomDashboard } from "@/components/v2/dashboard/custom/CustomDashboard";
import { warsawDay } from "@/components/v2/dashboard/MyTasksDashboard";
import { api } from "@/lib/api";
import {
  METRIC_CATALOG_QUERY_KEY,
  metricQueryKey,
  type MetricCatalog,
  type MetricResult,
} from "@/lib/api/dashboardMetrics";
import { myPeopleSummaryQueryKey } from "@/lib/api/myPeople";
import { BOARD_TASKS_QUERY_KEY, type BoardTasksResponse } from "@/lib/api/boardTasks";
import {
  USER_DASHBOARD_QUERY_KEY,
  type DashboardTile,
  type UserDashboardResponse,
} from "@/lib/api/userDashboard";
import { TILE_TEMPLATES } from "@/lib/dashboard-tiles/catalog";
import { useAuthStore } from "@/store/auth";

const tpl = (key: string) => TILE_TEMPLATES.find((t) => t.key === key)!;

function metricResult(over: Partial<MetricResult>): MetricResult {
  return {
    value: 0,
    previous_value: null,
    series: [],
    unit: "count",
    scope_applied: "me",
    notes: [],
    period: { key: "last_30_days", label: "30 dni", start: "2026-08-23", end: "2026-09-21" },
    ...over,
  };
}

const weeks = ["28.07", "04.08", "11.08", "18.08", "25.08", "01.09", "08.09", "15.09"];

const TILES: DashboardTile[] = [
  { id: "t1", type: "metric_number", x: 0, y: 0, w: 3, h: 2, config: tpl("cv_sent_week").config },
  { id: "t2", type: "metric_number", x: 3, y: 0, w: 3, h: 2, config: tpl("hired_month").config },
  { id: "t3", type: "metric_number", x: 6, y: 0, w: 3, h: 2, config: tpl("active_contracts").config },
  { id: "t4", type: "my_people", x: 9, y: 0, w: 3, h: 2, config: {} },
  { id: "t5", type: "metric_funnel", x: 0, y: 2, w: 6, h: 3, config: tpl("funnel").config },
  { id: "t6", type: "metric_chart", x: 6, y: 2, w: 6, h: 3, config: tpl("orders_ending").config },
  { id: "t7", type: "metric_chart", x: 0, y: 5, w: 8, h: 3, config: tpl("cv_sent_weekly_chart").config },
  { id: "t8", type: "calendar_today", x: 8, y: 5, w: 4, h: 3, config: {} },
  {
    id: "t9",
    type: "note",
    x: 0,
    y: 8,
    w: 4,
    h: 2,
    config: {
      title: "Na ten tydzień",
      text: "Oddzwonić do Nordei w sprawie dwóch CV.",
      links: [
        { label: "Moje rekrutacje", url: "/jobs" },
        { label: "Kalendarz", url: "/calendar" },
      ],
    },
  },
];

const CATALOG: MetricCatalog = {
  sources: [
    { key: "pipeline_moves", label: "Ruchy w pipeline", available: true, reason: null, measures: [{ key: "first_reach", label: "Liczba pierwszych wejść na etap", snapshot: false }], group_by: ["none", "week", "month", "client", "recruiter", "stage", "competence_category"], filters: ["client_ids", "competence_category_ids", "job_ids"], supports_author: true },
    { key: "candidates", label: "Kandydaci", available: true, reason: null, measures: [{ key: "new", label: "Nowi kandydaci w bazie", snapshot: false }], group_by: ["none", "week", "month", "recruiter", "competence_category"], filters: ["competence_category_ids"], supports_author: true },
    { key: "jobs", label: "Rekrutacje", available: true, reason: null, measures: [{ key: "open_now", label: "Rekrutacje otwarte teraz", snapshot: true }], group_by: ["none", "client", "recruiter", "competence_category"], filters: ["client_ids", "competence_category_ids"], supports_author: true },
    { key: "contracts", label: "Kontrakty", available: true, reason: null, measures: [{ key: "active_now", label: "Aktywne kontrakty teraz", snapshot: true }], group_by: ["none", "client"], filters: ["client_ids"], supports_author: false },
    { key: "orders", label: "Zamówienia", available: true, reason: null, measures: [{ key: "ending_30_days", label: "Kończące się w ciągu 30 dni", snapshot: true }], group_by: ["none", "client"], filters: ["client_ids"], supports_author: false },
    { key: "finance", label: "Finanse", available: false, reason: "Kwoty widzą Finanse, administrator i Delivery Lead dla swoich klientów.", measures: [{ key: "margin", label: "Marża miesięczna (PLN)", snapshot: false }], group_by: ["none", "month", "client"], filters: ["client_ids"], supports_author: false },
  ],
  authors: ["me", "team"],
  stages: [
    { key: "verified", label: "Zweryfikowani" },
    { key: "cv_sent", label: "CV wysłane" },
    { key: "interview", label: "Rozmowa" },
    { key: "client_interview", label: "Rozmowa z klientem" },
    { key: "acceptance", label: "Akceptacja" },
    { key: "hired", label: "Zatrudnieni" },
  ],
  periods: [
    { key: "last_7_days", label: "7 dni" },
    { key: "last_30_days", label: "30 dni" },
    { key: "last_8_weeks", label: "8 tygodni" },
    { key: "this_month", label: "ten miesiąc" },
  ],
};

// Przykładowa kolejka „Czeka na Ciebie" (dane fikcyjne).
const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();
const taskRow = (over: Partial<BoardTasksResponse["dz"][number]>): BoardTasksResponse["dz"][number] => ({
  kind: "dz",
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "Kandydat",
  job_id: 1,
  job_title: "Senior Java Developer",
  client_id: 11,
  client_name: "Nordea",
  since: daysAgo(1),
  process_state_version: 1,
  target_stage_def_id: 5,
  assignee_id: null,
  assignee_name: null,
  ...over,
});
const BOARD_TASKS: BoardTasksResponse = {
  window_days: 14,
  can_approve_dz: true,
  dz: [
    taskRow({ stage_id: 101, candidate_id: 201, candidate_name: "Joanna Wiśniewska", since: daysAgo(4) }),
    taskRow({ stage_id: 102, candidate_id: 202, candidate_name: "Tomasz Lewandowski", job_title: "Data Engineer", client_name: "PKO BP", since: daysAgo(2) }),
    taskRow({ stage_id: 103, candidate_id: 203, candidate_name: "Karolina Dąbrowska", job_title: "Tester Manualny", client_name: "Tauron", since: daysAgo(0) }),
  ],
  cpro_to_send: [
    taskRow({ kind: "cpro_to_send", stage_id: 111, candidate_id: 211, candidate_name: "Michał Wójcik", assignee_id: 1, assignee_name: "Artur Twardowski", since: daysAgo(1) }),
    taskRow({ kind: "cpro_to_send", stage_id: 112, candidate_id: 212, candidate_name: "Agnieszka Kamińska", job_title: "Business Analyst", since: daysAgo(3) }),
  ],
  cpro_sent: [
    taskRow({ kind: "cpro_sent", stage_id: 121, candidate_id: 221, candidate_name: "Paweł Zając", job_title: "PEGA Lead System Architect", since: daysAgo(6), target_stage_def_id: null }),
  ],
};

function seededClient(tiles: DashboardTile[]): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  qc.setQueryData<UserDashboardResponse>(USER_DASHBOARD_QUERY_KEY, {
    tiles,
    version: 3,
    dropped_tiles: [],
  });
  qc.setQueryData(METRIC_CATALOG_QUERY_KEY, CATALOG);
  qc.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, BOARD_TASKS);
  qc.setQueryData(["users-directory", "cpro-assignees"], [
    { id: 1, name: "Artur Twardowski" },
    { id: 7, name: "Marta Kowalczyk" },
    { id: 8, name: "Piotr Zieliński" },
  ]);
  qc.setQueryData(metricQueryKey(tpl("cv_sent_week").config.metric!), metricResult({ value: 14, previous_value: 10, series: [] }));
  qc.setQueryData(metricQueryKey(tpl("hired_month").config.metric!), metricResult({ value: 2, previous_value: 3 }));
  qc.setQueryData(metricQueryKey(tpl("active_contracts").config.metric!), metricResult({ value: 318, scope_applied: "all" }));
  qc.setQueryData(
    metricQueryKey(tpl("funnel").config.metric!),
    metricResult({
      value: 76,
      series: [
        { key: "verified", label: "Zweryfikowani", value: 42 },
        { key: "cv_sent", label: "CV wysłane", value: 21 },
        { key: "interview", label: "Rozmowa", value: 9 },
        { key: "client_interview", label: "Rozmowa z klientem", value: 5 },
        { key: "hired", label: "Zatrudnieni", value: 2 },
      ],
    }),
  );
  qc.setQueryData(
    metricQueryKey(tpl("orders_ending").config.metric!),
    metricResult({
      value: 9,
      scope_applied: "all",
      series: [
        { key: "1", label: "Nordea", value: 3 },
        { key: "2", label: "PKO BP", value: 2 },
        { key: "3", label: "Alior", value: 2 },
        { key: "4", label: "Orlen", value: 1 },
        { key: "5", label: "BIK", value: 1 },
      ],
    }),
  );
  qc.setQueryData(
    metricQueryKey(tpl("cv_sent_weekly_chart").config.metric!),
    metricResult({
      value: 83,
      previous_value: 71,
      series: [8, 11, 9, 12, 7, 10, 12, 14].map((v, i) => ({ key: String(i), label: weeks[i], value: v })),
    }),
  );
  qc.setQueryData(["dashboard", "calendar-today", warsawDay()], [
    { id: 1, title: "Rozmowa: Anna Zielińska", start_time: new Date().toISOString().slice(0, 10) + "T08:00:00Z", all_day: false, candidate_name: "Anna Zielińska", client_name: "Nordea" },
    { id: 2, title: "Screening telefoniczny", start_time: new Date().toISOString().slice(0, 10) + "T10:30:00Z", all_day: false, candidate_name: "Piotr Lis", client_name: null },
    { id: 3, title: "Preparation meeting", start_time: new Date().toISOString().slice(0, 10) + "T13:00:00Z", all_day: false, candidate_name: null, client_name: "Orlen" },
  ]);
  qc.setQueryData(myPeopleSummaryQueryKey, {
    total: 37,
    new_matches: 3,
    jobs_with_matches: 2,
    latest_matches: [],
    idle_count: 5,
    idle_top: [],
    idle_days: 30,
  });
  // Stałe klucze pickerów kreatora (`harness-seeds.test.ts`).
  qc.setQueryData(["dashboard-metric-clients"], []);
  qc.setQueryData(["competence-categories-active"], []);
  return qc;
}

export default function CustomDashboardPreview() {
  const [ready, setReady] = useState(false);
  const [variant, setVariant] = useState<"filled" | "empty">("filled");
  const [filled] = useState(() => seededClient(TILES));
  const [empty] = useState(() => seededClient([]));

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Rekruter",
        role: "recruiter",
        roles: ["recruiter", "delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      hydrated: true,
    });
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <ToastProvider>
      <div className="min-h-screen bg-background">
        <div className="flex gap-2 border-b border-border px-6 py-3 text-sm">
          <span className="text-muted-foreground">Podgląd:</span>
          {(["filled", "empty"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={variant === v}
              onClick={() => setVariant(v)}
              className={variant === v ? "font-semibold text-primary" : "text-foreground"}
            >
              {v === "filled" ? "Pulpit z kafelkami" : "Pusty pulpit"}
            </button>
          ))}
        </div>
        {/* Padding powłoki (`<main>` ma `p-4 md:p-6`) — pulpit nie dokłada własnego. */}
        <div className="p-4 md:p-6">
          <QueryClientProvider key={variant} client={variant === "filled" ? filled : empty}>
            <CustomDashboard />
          </QueryClientProvider>
        </div>
      </div>
    </ToastProvider>
  );
}
