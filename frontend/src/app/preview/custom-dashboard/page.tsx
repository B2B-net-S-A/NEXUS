"use client";

// Publiczny harness własnego pulpitu (0337): pusty start i pulpit z kafelkami.
// ZERO zapytań — każdy klucz jest zasiany, a interceptor odcina sieć, więc
// strona nie przerzuca na /login (pilnuje `harness-seeds.test.ts`).
// Zapis układu w podglądzie kończy się komunikatem o błędzie — to zamierzone.
//
// Domyślnie pulpit Head of Recruitment: „Czeka na Ciebie” zaczyna się od
// propozycji automatu przydziału (trzy przypadki: osoba z 1. priorytetem,
// osoba bez requestów, osoba na urlopie) z banerem o braku
// danych o urlopach; „Zmień” otwiera listę osób z zasianego obłożenia.
// Pod propozycjami „Nowe rekrutacje — kto prowadzi”: prowadzący z automatu,
// wskazany ręcznie, propozycja czekająca na akceptację, automat w trakcie
// przydziału, „Przyjmujemy kandydatów” i rekrutacja bez prowadzącego. W wariantach
// „CV w drodze” (nic nie czeka) ta lista stoi sama, we własnej ramce.
// „Rekrutacje do dokończenia albo zamknięcia” (stary szkic z odliczaniem do
// zamknięcia, rekrutacja bez przekazania, niedokończony formularz) stoi
// w panelu wariantu „Pulpit z kafelkami”, a w wariancie „CV w drodze: pasek”
// — sama, we własnej ramce.
// `?as=recruiter|tcm|dl|dlr|hor|admin|finance` (04.10.2026) — persona roli;
// domyślny wariant „Układ roli” pokazuje pulpit konta bez zapisanego układu
// (`uses_role_layout`) i „Czeka na Ciebie” z przepływem rekrutacji (rekruter,
// TCM, DL) albo pracą Finansów. Propozycje i „kto prowadzi” — Head i admin.

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
import { MY_CLIENTS_CARDS_QUERY_KEY } from "@/components/v2/dashboard/MyClientsAlertsPanel";
import {
  MY_RECRUITMENTS_QUERY_KEY,
  type MyRecruitmentRow,
} from "@/components/v2/dashboard/custom/MyRecruitmentsTile";
import { MY_WEEK_QUERY_KEY } from "@/components/v2/dashboard/custom/MyWeekTile";
import {
  SYSTEM_STATUS_QUERY_KEY,
  type HealthResponse,
} from "@/components/v2/dashboard/custom/SystemStatusTile";
import {
  TEAM_SIGNALS_QUERY_KEY,
  type TeamSignal,
} from "@/components/v2/dashboard/custom/TeamSignalsTile";
import { interviewCycleQueryKey } from "@/lib/api/interviewCycle";
import { ORDER_CHANGES_SUMMARY_KEY } from "@/lib/api/finance";
import type { MyKpiPanel } from "@/lib/api";
import type { CycleOverview } from "@/lib/interview-cycle";
import {
  BOARD_TASKS_QUERY_KEY,
  CPRO_SENDER_QUERY_KEY,
  type AllocationProposalRow,
  type BoardTaskRow,
  type BoardTasksResponse,
  type CproSender,
  type CvInTransit,
  type CvTransitRow,
  type FinanceBlock,
  type FlowBlock,
  type NewJobLeadRow,
  type PendingJobs,
  type UnfinishedJobForm,
} from "@/lib/api/boardTasks";
import {
  REQUEST_BOARD_QUERY_KEY,
  type LoadPerson,
  type RequestBoard,
} from "@/lib/api/requestAllocation";
import {
  USER_DASHBOARD_QUERY_KEY,
  type DashboardTile,
  type UserDashboardResponse,
} from "@/lib/api/userDashboard";
import { TILE_TEMPLATES } from "@/lib/dashboard-tiles/catalog";
import { candidateContactQueryKeys } from "@/lib/candidate-contact";
import type { UserRole } from "@/store/auth";
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
    { key: "finance", label: "Finanse", available: false, reason: "Kwoty widzą osoby z uprawnieniem „Stawki i kwoty: podgląd” (Delivery Lead: u swoich klientów).", measures: [{ key: "margin", label: "Marża miesięczna (PLN)", snapshot: false }], group_by: ["none", "month", "client"], filters: ["client_ids"], supports_author: false },
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
const taskRow = (over: Partial<BoardTaskRow>): BoardTaskRow => ({
  kind: "dl_review",
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "Kandydat",
  job_id: 1,
  job_title: "Senior Java Developer",
  client_id: 11,
  client_name: "Bank Północny",
  since: daysAgo(1),
  process_state_version: 1,
  target_stage_def_id: 5,
  assignee_id: null,
  assignee_name: null,
  ...over,
});
const BOARD_TASKS: BoardTasksResponse = {
  window_days: 14,
  can_send_to_client: true,
  can_set_cpro_sender: true,
  dl_review_window_days: 30,
  dl_review: [
    taskRow({ stage_id: 101, candidate_id: 201, candidate_name: "Joanna Wiśniewska", client_name: "Bank Kappa", since: daysAgo(4), qc_status: "passed", card_status: "complete", card_missing: 0 }),
    taskRow({ stage_id: 102, candidate_id: 202, candidate_name: "Tomasz Lewandowski", job_title: "Data Engineer", client_name: "Bank Kappa", since: daysAgo(2), qc_status: "failed", qc_blocking_failed: 2, card_status: "partial", card_missing: 3 }),
    taskRow({ stage_id: 103, candidate_id: 203, candidate_name: "Karolina Dąbrowska", job_title: "Tester Manualny", client_name: "Energetyka Wzorcowa", since: daysAgo(0), qc_status: "overridden" }),
  ],
  cpro_to_send: [
    taskRow({ kind: "cpro_to_send", stage_id: 111, candidate_id: 211, candidate_name: "Michał Wójcik", assignee_id: 1, assignee_name: "Adam Wzorcowy", since: daysAgo(1) }),
    taskRow({ kind: "cpro_to_send", stage_id: 112, candidate_id: 212, candidate_name: "Agnieszka Kamińska", job_title: "Business Analyst", since: daysAgo(3) }),
  ],
  cpro_sent: [
    taskRow({ kind: "cpro_sent", stage_id: 121, candidate_id: 221, candidate_name: "Paweł Zając", job_title: "PEGA Lead System Architect", since: daysAgo(6), target_stage_def_id: null }),
  ],
};

// Propozycje automatu przydziału do akceptacji (dane fikcyjne). Kolejność jak
// z serwera: P1 na górze, potem najdłużej czekające.
const proposal = (over: Partial<AllocationProposalRow>): AllocationProposalRow => ({
  job_id: 1,
  title: "Request",
  client_name: "Bank Północny",
  category_id: 2,
  category_name: "Development",
  category_slug: "software_development",
  delivery_lead_name: "Marta Kowalczyk",
  priority_level: "p2",
  deadline: null,
  sent: 0,
  user_id: 1,
  user_name: "Osoba",
  fit: "first",
  load: 0,
  leave_until: null,
  base_matches: null,
  proposed_at: daysAgo(0),
  ...over,
});
const ALLOCATION_PROPOSALS: AllocationProposalRow[] = [
  proposal({ job_id: 301, title: "Full Stack Java Developer · Spring Boot", priority_level: "p1", deadline: "2026-10-10", user_id: 41, user_name: "Marek Wzorcowy", fit: "first", load: 2, proposed_at: daysAgo(1) }),
  proposal({ job_id: 302, title: "Administrator chmury · Azure, Terraform", client_name: "Fundusz Przykładowy", category_id: 1, category_name: "Infra & Operations & Security / Data & AI", category_slug: "infrastructure_operations", delivery_lead_name: "Piotr Zieliński", user_id: 42, user_name: "Ewa Fikcyjna", fit: "first", load: 0, base_matches: 22 }),
  proposal({ job_id: 303, title: "Tester automatyzujący · Python, Robot Framework", category_id: 4, category_name: "QA", category_slug: "security_quality", sent: 1, user_id: 43, user_name: "Tomasz Makietowy", fit: "other", load: 4, leave_until: "2026-10-09" }),
];

// „Nowe rekrutacje — kto prowadzi” (dane fikcyjne): po jednym wierszu na każdy
// stan prowadzącego. Lista informacyjna — nie dokłada nic do „Czeka na Ciebie”.
const jobLead = (over: Partial<NewJobLeadRow>): NewJobLeadRow => ({
  job_id: 1,
  title: "Rekrutacja",
  client_name: "Bank Północny",
  category_id: 2,
  category_name: "Development",
  category_slug: "software_development",
  participants: 6,
  priority_level: "p2",
  delivery_lead_name: "Marta Kowalczyk",
  handed_off_at: daysAgo(0),
  lead_user_id: null,
  lead_name: null,
  lead_role: null,
  lead_source: null,
  assigned_by_name: null,
  proposed: false,
  pending_reason: null,
  ...over,
});
const NEW_JOB_LEADS: NewJobLeadRow[] = [
  jobLead({ job_id: 311, title: "Backend Developer · Kotlin, Spring", priority_level: "p1", lead_user_id: 45, lead_name: "Julia Testowa", lead_role: "recruiter", lead_source: "auto" }),
  jobLead({ job_id: 312, title: "Inżynier danych · Spark, Airflow", client_name: "Fundusz Przykładowy", category_id: 1, category_name: "Infra & Operations & Security / Data & AI", category_slug: "infrastructure_operations", participants: 4, delivery_lead_name: "Piotr Zieliński", lead_user_id: 44, lead_name: "Kinga Przykładowa", lead_role: "recruiter", lead_source: "manual", assigned_by_name: "Piotr Zieliński", handed_off_at: daysAgo(1) }),
  jobLead({ job_id: 301, title: "Full Stack Java Developer · Spring Boot", priority_level: "p1", lead_user_id: 41, lead_name: "Marek Wzorcowy", lead_role: "recruiter", lead_source: "auto", proposed: true, handed_off_at: daysAgo(1) }),
  jobLead({ job_id: 313, title: "Analityk biznesowy · bankowość", client_name: "Bank Kappa", category_id: 5, category_name: "Management & Delivery (PM & BA)", category_slug: "management_delivery", participants: 3, pending_reason: "assigning" }),
  jobLead({ job_id: 314, title: "Tester manualny · aplikacje mobilne", client_name: "Ubezpieczenia Wzorcowe", category_id: 4, category_name: "QA", category_slug: "security_quality", participants: 1, priority_level: "accepting", pending_reason: "passive", handed_off_at: daysAgo(2) }),
  jobLead({ job_id: 315, title: "Administrator sieci · Cisco", client_name: "Energetyka Wzorcowa", category_id: null, category_name: null, category_slug: null, participants: 0, pending_reason: "none", handed_off_at: daysAgo(3) }),
  jobLead({ job_id: 316, title: "Projektant UX · aplikacje webowe", client_name: "Bank Kappa", category_id: 2, category_name: "Development", category_slug: "software_development", participants: 0, pending_reason: "not_handed_off", handed_off_at: daysAgo(5) }),
];

// Obłożenie dla listy „Zmień” — te same osoby co w propozycjach i kilka wolnych.
const loadPerson = (over: Partial<LoadPerson> & Pick<LoadPerson, "user_id" | "name">): LoadPerson => ({
  count: 0,
  proposed: 0,
  leave_until: null,
  requests: [],
  ...over,
});
const REQUEST_BOARD: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [],
  requests: [],
  load: [
    loadPerson({ user_id: 44, name: "Kinga Przykładowa", count: 4 }),
    loadPerson({ user_id: 43, name: "Tomasz Makietowy", count: 4, proposed: 1, leave_until: "2026-10-09" }),
    loadPerson({ user_id: 41, name: "Marek Wzorcowy", count: 2, proposed: 1 }),
    loadPerson({ user_id: 45, name: "Julia Testowa", count: 1 }),
    loadPerson({ user_id: 42, name: "Ewa Fikcyjna", count: 0, proposed: 1 }),
    loadPerson({ user_id: 46, name: "Maja Próbna", count: 0 }),
  ],
  changes: [],
};

type Persona = "hor" | "recruiter" | "tcm" | "dl" | "dlr" | "admin" | "finance";

const PERSONAS: Record<Persona, { label: string; roles: UserRole[] }> = {
  recruiter: { label: "Rekruter", roles: ["recruiter"] },
  tcm: { label: "Talent Community Manager", roles: ["talent_community_manager"] },
  dl: { label: "Delivery Lead", roles: ["delivery_lead"] },
  dlr: { label: "Delivery Lead + Rekruter", roles: ["delivery_lead", "recruiter"] },
  hor: { label: "Head of Recruitment", roles: ["head_of_recruitment", "delivery_lead"] },
  admin: { label: "Administrator", roles: ["admin"] },
  finance: { label: "Finanse", roles: ["finance"] },
};

function parsePersona(value: string | null): Persona {
  return value && value in PERSONAS ? (value as Persona) : "hor";
}

// „Twój ruch” (04.10.2026) — przepływ rekrutacji i praca Finansów (dane fikcyjne).
const flowPair = (over: Partial<FlowBlock["claimed"][number]>): FlowBlock["claimed"][number] => ({
  candidate_id: 1,
  candidate_name: "Kandydat",
  job_id: 501,
  job_title: "Senior Java Developer",
  job_working_title: null,
  client_name: "Bank Północny",
  since: daysAgo(1),
  claimed_until: null,
  missing: [],
  qc_status: null,
  ...over,
});
const FLOW: FlowBlock = {
  applies: true,
  new_requests: [
    { job_id: 504, job_title: "Programista Python · Django", job_working_title: "Python · Django · 4+ lat", client_name: "Bank Kappa", assigned_at: daysAgo(0), assigned_by_name: "Piotr Zieliński" },
    { job_id: 505, job_title: "Analityk systemowy · UML", job_working_title: null, client_name: "Fundusz Przykładowy", assigned_at: daysAgo(2), assigned_by_name: null },
  ],
  new_request_days: 3,
  postings: [
    { job_id: 501, job_title: "Senior Java Developer", client_name: "Bank Północny", count: 46, oldest_at: daysAgo(9) },
    { job_id: 502, job_title: "Tester automatyzujący · Python", client_name: "Bank Kappa", count: 18, oldest_at: daysAgo(4) },
    { job_id: 503, job_title: "Administrator chmury · Azure", client_name: "Fundusz Przykładowy", count: 7, oldest_at: daysAgo(2) },
  ],
  postings_total: 71,
  claimed: [
    flowPair({ candidate_id: 601, candidate_name: "Marta Fikcyjna", claimed_until: new Date(Date.now() + 5 * 3_600_000).toISOString() }),
  ],
  screening: [
    flowPair({ candidate_id: 602, candidate_name: "Piotr Wzorcowy", missing: ["sheet", "rate"], since: daysAgo(3) }),
    flowPair({ candidate_id: 603, candidate_name: "Alicja Makietowa", job_id: 502, job_title: "Tester automatyzujący · Python", client_name: "Bank Kappa", missing: ["rate"] }),
  ],
  verified: [flowPair({ candidate_id: 604, candidate_name: "Kamil Przykładowy", since: daysAgo(2) })],
  waiting_client: [],
  waiting_client_days: 7,
  unsigned_contracts: [],
  order_mail_review: 0,
};
const DL_FLOW: FlowBlock = {
  ...FLOW,
  waiting_client: [
    flowPair({ candidate_id: 611, candidate_name: "Ewa Zmyślona", since: daysAgo(11) }),
    flowPair({ candidate_id: 612, candidate_name: "Jan Fikcyjny", job_id: 503, job_title: "Administrator chmury · Azure", client_name: "Fundusz Przykładowy", since: daysAgo(8) }),
  ],
  unsigned_contracts: [
    { id: 71, contract_number: "1734/2026", partner_name: "Kod i Chmura Jan Fikcyjny", client_name: "Bank Północny", created_at: daysAgo(4) },
  ],
  order_mail_review: 2,
};
const FINANCE: FinanceBlock = {
  gaps_open: 3,
  pdfs_new: 12,
  order_mail_failed: 1,
  hired_without_order: [flowPair({ candidate_id: 621, candidate_name: "Robert Makietowy", since: daysAgo(6) })],
  hired_without_order_total: 1,
};

const TODAY_ISO = new Date().toISOString().slice(0, 10);
const cyclePair = (id: number, name: string, client: string) => ({
  candidate_id: id,
  candidate_name: name,
  candidate_email: null,
  job_id: 501,
  job_title: "Senior Java Developer",
  client_id: 11,
  client_name: client,
});
const CYCLE: CycleOverview = {
  generated_at: new Date().toISOString(),
  scope: "mine",
  call_window_minutes: 30,
  items: [],
  agenda: [
    { ...cyclePair(701, "Anna Zielińska", "Bank Północny"), kind: "prep", start: `${TODAY_ISO}T07:30:00Z`, end: `${TODAY_ISO}T08:00:00Z`, event_id: 1, slot_request_id: null, online_meeting_url: null, done: true },
    { ...cyclePair(701, "Anna Zielińska", "Bank Północny"), kind: "interview", start: `${TODAY_ISO}T10:00:00Z`, end: `${TODAY_ISO}T11:00:00Z`, event_id: 2, slot_request_id: null, online_meeting_url: null, done: false },
    { ...cyclePair(702, "Tomasz Wzorcowy", "Bank Kappa"), kind: "prep2", start: `${TODAY_ISO}T13:00:00Z`, end: `${TODAY_ISO}T13:30:00Z`, event_id: 3, slot_request_id: null, online_meeting_url: null, done: false },
  ],
  todos: [
    { ...cyclePair(703, "Karolina Fikcyjna", "Bank Kappa"), kind: "debrief_overdue", priority: 1, due: daysAgo(1), event_id: 4, slot_request_id: null },
  ],
  truncated: false,
};

const MY_WEEK: MyKpiPanel = {
  role: "recruiter",
  applies: true,
  weryfikacje: { day: 2, week: 9, month: 31 },
  rekomendacje: { day: 1, week: 6, month: 19 },
  interview_month: 5,
  akceptacje_month: 1,
  placementy_month: 1,
  cv_to_base: null,
  precision: { value_pct: 72, verified: 25, sent: 18, target_pct: 75, window_days: 30 },
  target_verifications_daily: 4,
  target_placements_monthly: 1,
  target_cv_added_daily: null,
  target_precision_pct: 75,
};

const TEAM_SIGNALS: { items: TeamSignal[] } = {
  items: [
    { kind: "no_one_sent", count: 6, label: "rekrutacji otwartych ponad 14 dni bez wysłanego CV", href: "/jobs?open=1&sent=none" },
    { kind: "overdue", count: 3, label: "rekrutacje po terminie", href: "/jobs?open=1&deadline=overdue" },
    { kind: "stale_postings", count: 214, label: "osób czeka w Ogłoszeniach ponad 3 dni" },
    { kind: "stale_jobs", count: 4, label: "rekrutacje bez ruchu od 14 dni", report: "stale_jobs" },
  ],
};

const HEALTH: HealthResponse = {
  status: "healthy",
  version: "cb15211a0c",
  checks: {
    traffit: "degraded",
    order_mail: "healthy",
    background_tasks: "healthy",
    migrations: "healthy",
    m365_mail: "unknown",
    qdrant: "healthy",
    voyage: "healthy",
    anthropic: "healthy",
  },
};

const recruitmentRow = (over: Partial<MyRecruitmentRow>): MyRecruitmentRow => ({
  id: 501,
  title: "Senior Java Developer",
  client_name: "Bank Północny",
  deadline: TODAY_ISO,
  delivery_lead_id: 1,
  recruiters: [],
  stage_breakdown: { posting: 46, new: 4, screening: 2, verified: 1, cv_sent: 3, client_interview: 1 },
  ...over,
});
const MY_RECRUITMENTS = {
  total: 3,
  items: [
    recruitmentRow({}),
    recruitmentRow({ id: 502, title: "Tester automatyzujący · Python", client_name: "Bank Kappa", deadline: null, stage_breakdown: { posting: 18, new: 2, screening: 1 } }),
    recruitmentRow({ id: 503, title: "Administrator chmury · Azure", client_name: "Fundusz Przykładowy", deadline: "2026-11-15", stage_breakdown: { new: 3, cv_sent: 2 } }),
  ],
};

const transitRow = (over: Partial<CvTransitRow>): CvTransitRow => ({
  kind: "in_review",
  stage_id: 301,
  candidate_id: 401,
  candidate_name: "Adam Wrona",
  job_id: 900,
  job_title: "Java Developer",
  job_working_title: "Java · Spring · 5+ lat",
  client_name: "Bank Kappa",
  since: daysAgo(1),
  actor_name: null,
  holder_name: null,
  reason: null,
  ...over,
});

const TRANSIT_INFO: Pick<CvInTransit, "in_review" | "sent"> = {
  in_review: [
    transitRow({ stage_id: 311, candidate_id: 411, candidate_name: "Tomasz Żak", job_working_title: "DevOps · AWS · Terraform", client_name: "Energetyka Wzorcowa", holder_name: "Jan Dąb", since: daysAgo(3) }),
    transitRow({ stage_id: 312, candidate_id: 412, candidate_name: "Karolina Mróz", holder_name: "Marta Kowalczyk", since: daysAgo(1) }),
    transitRow({ kind: "cpro_queue", stage_id: 313, candidate_id: 413, candidate_name: "Michał Kruk", job_working_title: "Analityk biznesowy · bankowość", client_name: "Bank Północny", holder_name: "Adam Wzorcowy", since: daysAgo(0) }),
  ],
  sent: [
    transitRow({ kind: "sent", stage_id: 321, candidate_id: 421, candidate_name: "Anna Sroka", actor_name: "Marta Kowalczyk", since: daysAgo(1) }),
    transitRow({ kind: "sent", stage_id: 322, candidate_id: 422, candidate_name: "Paweł Gil", job_working_title: "Tester automatyzujący · Selenium", client_name: "Ubezpieczenia Wzorcowe", actor_name: "Jan Dąb", since: daysAgo(4) }),
  ],
};

function transit(returned: CvTransitRow[], info = TRANSIT_INFO): CvInTransit {
  return {
    returned,
    ...info,
    returned_total: returned.length,
    in_review_total: info.in_review.length,
    sent_total: info.sent.length,
    returned_window_days: 14,
    sent_window_days: 7,
  };
}

const TRANSIT_RETURNED = transit([
  transitRow({ kind: "rejected_by_dl", stage_id: 331, candidate_id: 431, candidate_name: "Adam Wrona", actor_name: "Marta Kowalczyk", reason: "stawka ponad budżet", since: daysAgo(0) }),
  transitRow({ kind: "sent_back", stage_id: 332, candidate_id: 432, candidate_name: "Julia Bąk", job_working_title: "Tester automatyzujący · Selenium", client_name: "Ubezpieczenia Wzorcowe", actor_name: "Jan Dąb", remark: "Dopisz Selenium Grid do ostatniego projektu i popraw daty w drugiej roli.", since: daysAgo(1) }),
]);

// „Rekrutacje do dokończenia albo zamknięcia” (dane fikcyjne): stary szkic,
// który system zamknie sam, i rekrutacja opublikowana bez przekazania do
// searchu. Termin zamknięcia za kilka dni od dziś (`RRRR-MM-DD`).
const dayAhead = (d: number) => new Date(Date.now() + d * 86_400_000).toISOString().slice(0, 10);
const PENDING_JOBS: PendingJobs = {
  autoclose_on: dayAhead(5),
  items: [
    {
      job_id: 801,
      title: "Analityk danych",
      client_name: "Bank Kappa",
      kind: "legacy_draft",
      created_at: daysAgo(12),
      delivery_lead_name: "Marta Kowalczyk",
      missing: ["Budżet PLN/h", "Tryb pracy", "Pytania screeningowe", "Wymagania do wyszukiwania w bazie"],
    },
    {
      job_id: 802,
      title: "Tester automatyzujący",
      client_name: "Ubezpieczenia Wzorcowe",
      kind: "published_not_handed_off",
      created_at: daysAgo(6),
      delivery_lead_name: "Jan Dąb",
      missing: ["Opis projektu"],
    },
  ],
};
const UNFINISHED_FORMS: UnfinishedJobForm[] = [
  { id: 1, label: "Java Developer", client_name: "Bank Północny", updated_at: daysAgo(3) },
];

const NO_TASKS: BoardTasksResponse = {
  window_days: 14,
  dl_review_window_days: 30,
  dl_review: [],
  cpro_to_send: [],
  cpro_sent: [],
};

type Variant = "role" | "filled" | "empty" | "bar" | "bar-empty";

const VARIANT_LABEL: Record<Variant, string> = {
  role: "Układ roli",
  filled: "Pulpit z kafelkami",
  empty: "Pusty pulpit",
  bar: "CV w drodze: pasek",
  "bar-empty": "CV w drodze: pusto",
};

function seededClient(
  tiles: DashboardTile[],
  boardTasks: BoardTasksResponse,
  persona: Persona,
  roleLayout = false,
): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  qc.setQueryData<UserDashboardResponse>(USER_DASHBOARD_QUERY_KEY, {
    tiles,
    version: roleLayout ? 0 : 3,
    dropped_tiles: [],
    uses_role_layout: roleLayout,
  });
  qc.setQueryData(METRIC_CATALOG_QUERY_KEY, CATALOG);
  // Propozycje i „Nowe rekrutacje — kto prowadzi” dostaje wyłącznie osoba,
  // która o przydziale decyduje — jak z serwera.
  const decides = persona === "hor" || persona === "admin";
  const withFlow: BoardTasksResponse = {
    ...boardTasks,
    flow:
      persona === "dl" || persona === "dlr"
        ? DL_FLOW
        : persona === "recruiter" || persona === "tcm"
          ? FLOW
          : null,
    finance: persona === "finance" ? FINANCE : null,
    ...(persona === "finance" ? { cv_in_transit: null, dl_review: [], cpro_to_send: [], cpro_sent: [] } : {}),
    // Rekrutacje do dokończenia serwer daje tylko DL-owi, Headowi i adminowi.
    ...(persona === "dl" || persona === "dlr" || decides ? {} : { pending_jobs: null }),
  };
  qc.setQueryData<BoardTasksResponse>(
    BOARD_TASKS_QUERY_KEY,
    decides
      ? {
          ...withFlow,
          can_decide_proposals: true,
          allocation_leave_known: false,
          allocation_proposals: ALLOCATION_PROPOSALS,
          new_job_leads: NEW_JOB_LEADS,
        }
      : { ...withFlow, can_decide_proposals: false },
  );
  // Nowe kafelki układu ról (04.10.2026).
  qc.setQueryData<CycleOverview>(interviewCycleQueryKey("mine"), CYCLE);
  qc.setQueryData<CycleOverview>(interviewCycleQueryKey("jobs"), { ...CYCLE, scope: "jobs" });
  qc.setQueryData<MyKpiPanel>(MY_WEEK_QUERY_KEY, MY_WEEK);
  qc.setQueryData(TEAM_SIGNALS_QUERY_KEY, TEAM_SIGNALS);
  qc.setQueryData<HealthResponse>(SYSTEM_STATUS_QUERY_KEY, HEALTH);
  qc.setQueryData(MY_RECRUITMENTS_QUERY_KEY, MY_RECRUITMENTS);
  qc.setQueryData(MY_CLIENTS_CARDS_QUERY_KEY, { cards: [], total: 0 });
  qc.setQueryData(ORDER_CHANGES_SUMMARY_KEY, {
    period: { year: 2026, month: 10, label: "październik 2026" },
    tabs: {},
    todo: 7,
  });
  // Każdy szablon metryki z katalogu ma wynik — układy ról sięgają po różne.
  for (const t of TILE_TEMPLATES) {
    if (!t.config.metric) continue;
    const key = metricQueryKey(t.config.metric);
    if (qc.getQueryData(key) !== undefined) continue;
    qc.setQueryData(key, metricResult({ value: 12, previous_value: 9 }));
  }
  // „Zmień” czyta obłożenie z pulpitu „Requesty i obłożenie”. Znacznik czasu
  // w przyszłości: dane nigdy nie są „stare”, więc otwarcie listy nie próbuje
  // ich odświeżyć (zero zapytań).
  qc.setQueryData<RequestBoard>(REQUEST_BOARD_QUERY_KEY, REQUEST_BOARD, {
    updatedAt: Date.now() + 24 * 60 * 60 * 1000,
  });
  qc.setQueryData<CproSender>(CPRO_SENDER_QUERY_KEY, {
    user_id: 1,
    user_name: "Adam Wzorcowy",
    until: null,
    fallback_user_id: null,
    fallback_user_name: null,
    set_by_name: "Adam Wzorcowy",
    set_at: daysAgo(3),
    can_set: true,
  });
  qc.setQueryData(["users-directory", "cpro-assignees"], [
    { id: 1, name: "Adam Wzorcowy" },
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
        { key: "1", label: "Bank Północny", value: 3 },
        { key: "2", label: "Bank Kappa", value: 2 },
        { key: "3", label: "Bank Lambda", value: 2 },
        { key: "4", label: "Paliwa Przykładowe", value: 1 },
        { key: "5", label: "Biuro Gamma", value: 1 },
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
    { id: 1, title: "Rozmowa: Anna Zielińska", start_time: new Date().toISOString().slice(0, 10) + "T08:00:00Z", all_day: false, candidate_name: "Anna Zielińska", client_name: "Bank Północny" },
    { id: 2, title: "Screening telefoniczny", start_time: new Date().toISOString().slice(0, 10) + "T10:30:00Z", all_day: false, candidate_name: "Piotr Lis", client_name: null },
    { id: 3, title: "Preparation meeting", start_time: new Date().toISOString().slice(0, 10) + "T13:00:00Z", all_day: false, candidate_name: null, client_name: "Paliwa Przykładowe" },
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
  // Kontakt z kandydatem włączony — kafelki TCM i nadzoru kontaktu u Heada.
  qc.setQueryData(candidateContactQueryKeys.status(), {
    enabled: true,
    assignment_enabled: true,
    traffit_intake_enabled: true,
  });
  qc.setQueryData(candidateContactQueryKeys.queue(), {
    items: [],
    utilization: { used: 6, capacity: 20 },
  });
  qc.setQueryData(candidateContactQueryKeys.oversight(), {
    counters: { overdue: 2, unassigned: 1, awaiting_capacity: 0, blocked_no_phone: 3 },
    items: [],
  });
  qc.setQueryData(["competence-categories-active"], []);
  return qc;
}

export default function CustomDashboardPreview() {
  const [persona, setPersona] = useState<Persona | null>(null);
  const [variant, setVariant] = useState<Variant>("role");
  const [clients, setClients] = useState<Record<Variant, QueryClient> | null>(null);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const as = parsePersona(new URLSearchParams(window.location.search).get("as"));
    const meta = PERSONAS[as];
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: `Preview ${meta.label}`,
        role: meta.roles[0],
        roles: meta.roles,
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      realUser: null,
      hydrated: true,
    });
    setClients({
      role: seededClient([], { ...NO_TASKS, cv_in_transit: TRANSIT_RETURNED, pending_jobs: PENDING_JOBS }, as, true),
      filled: seededClient(
        TILES,
        {
          ...BOARD_TASKS,
          cv_in_transit: TRANSIT_RETURNED,
          pending_jobs: PENDING_JOBS,
          unfinished_forms: UNFINISHED_FORMS,
        },
        as,
      ),
      empty: seededClient([], { ...BOARD_TASKS, cv_in_transit: TRANSIT_RETURNED }, as),
      bar: seededClient(
        TILES,
        { ...NO_TASKS, cv_in_transit: transit([]), pending_jobs: PENDING_JOBS, unfinished_forms: UNFINISHED_FORMS },
        as,
      ),
      "bar-empty": seededClient(
        TILES,
        { ...NO_TASKS, cv_in_transit: transit([], { in_review: [], sent: [] }) },
        as,
      ),
    });
    setPersona(as);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!persona || !clients) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <ToastProvider>
      <div className="min-h-screen bg-background">
        <div className="flex flex-wrap gap-2 border-b border-border px-6 py-3 text-sm">
          <span className="text-muted-foreground">Podgląd:</span>
          {(Object.keys(VARIANT_LABEL) as Variant[]).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={variant === v}
              onClick={() => setVariant(v)}
              className={variant === v ? "font-semibold text-primary" : "text-foreground"}
            >
              {VARIANT_LABEL[v]}
            </button>
          ))}
          <span className="ml-auto flex flex-wrap gap-x-3 text-muted-foreground">
            {(Object.keys(PERSONAS) as Persona[]).map((p) => (
              <a
                key={p}
                href={`?as=${p}`}
                aria-current={persona === p ? "page" : undefined}
                className={persona === p ? "font-semibold text-primary" : "hover:underline"}
              >
                {PERSONAS[p].label}
              </a>
            ))}
          </span>
        </div>
        {/* Padding powłoki (`<main>` ma `p-4 md:p-6`) — pulpit nie dokłada własnego. */}
        <div className="p-4 md:p-6">
          <QueryClientProvider key={variant} client={clients[variant]}>
            <CustomDashboard />
          </QueryClientProvider>
        </div>
      </div>
    </ToastProvider>
  );
}
