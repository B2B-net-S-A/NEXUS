/**
 * Fikcyjne odpowiedzi ekranów, które w lekcji nowości czytają prawdziwe API
 * (nie zestaw Poligonu): bank pytań, Insights, Szkolenia (bramka Kadr).
 * Na produkcji mają tam dane firmy; w `lessons-solo.spec.ts` podstawiony backend
 * bez nich dawał 404 i pusty ekran, więc etapu „sam” nie dało się sprawdzić.
 *
 * Dane wymyślone, bez prawdziwych osób i firm (repo jest publiczne). Typy z
 * aplikacji: zmiana kształtu odpowiedzi ekranu = błąd kompilacji tutaj.
 */
import type { HrConfig, HrModuleKey } from "../../src/lib/api/hr";
import type { TeamActivityResponse } from "../../src/lib/insights-api";
import type { LostReviewResponse, LostStage } from "../../src/lib/lost-review";
import type { BankQuestion } from "../../src/lib/question-bank";

import { SCREENS_CONTRACTS } from "./lesson-screens-contracts";
import { SCREENS_FINANCE } from "./lesson-screens-finance";
import { SCREENS_SALES } from "./lesson-screens-sales";

const MODULES: Record<HrModuleKey, boolean> = {
  people: false,
  leave: false,
  time: false,
  payroll: false,
  lifecycle: false,
  care: false,
  cases: false,
  equipment: false,
  settlements: false,
  approvals: false,
  back_office: false,
};

/** Program „Ludzi w NEXUSIE” włączony jak na produkcji (`HR_PROGRAM_ENABLED`), moduły zamknięte. */
const HR_CONFIG: HrConfig = {
  program: true,
  modules: MODULES,
  open_modules: MODULES,
  me: {
    has_profile: false,
    employment_status: null,
    is_manager: false,
    direct_reports: 0,
    is_admin: false,
    people_admin: false,
    payroll: false,
    equipment: false,
    cases: false,
  },
} as HrConfig;

const QUESTION = (id: number, text: string, managers: string[]): BankQuestion => ({
  id,
  text,
  client_id: 990501,
  client_name: "Bank Północny",
  source: "debrief",
  roles: [],
  managers,
  asked_count: 2,
  last_asked_at: "2026-11-20T10:00:00+00:00",
  answer: null,
  answer_source: null,
});

const STAGES: Record<LostStage, number> = { no_cv: 0, cv_only: 1, interview: 1, acceptance: 0 };

const LOST_REVIEW: LostReviewResponse = {
  period: { kind: "month", start: "2026-11-01", end: "2026-11-30" },
  period_label: "listopad 2026",
  since: "2026-11-01",
  counts: { won: 1, lost: 2, competitor: 1, idle: 1 },
  hit_ratio: 0.33,
  known: 1,
  why_filled: 1,
  stages: STAGES,
  compare: {
    won: { count: 1, first_cv_days: 3, cvs: 4, interview_share: 0.5 },
    lost: { count: 2, first_cv_days: 6, cvs: 2, interview_share: 0.25 },
  },
  trend: [],
  why_counts: [{ key: "competitor_faster", label: "Konkurent był szybszy", count: 1 }],
  source_counts: { client: 1, ours: 0, unknown: 0 },
  client_verdicts: [],
  clients: [],
  jobs: [
    {
      job_id: 990002,
      title: "Analityk ryzyka kredytowego",
      client_id: 990501,
      client_name: "Bank Północny",
      dl_id: 990902,
      dl_name: "Anna Poligonowa",
      outcome: "competitor",
      stage: "interview",
      closed_at: "2026-11-18",
      days_open: 21,
      days_first_cv: 6,
      cvs: 2,
      interviews: 1,
      client_verdicts: [],
      notes: null,
      why: [],
      source: null,
      ask_pending: false,
    },
    {
      job_id: 990003,
      title: "Tester automatyzujący",
      client_id: 990501,
      client_name: "Bank Północny",
      dl_id: 990902,
      dl_name: "Anna Poligonowa",
      outcome: "idle",
      stage: "cv_only",
      closed_at: "2026-11-12",
      days_open: 30,
      days_first_cv: 9,
      cvs: 1,
      interviews: 0,
      client_verdicts: [],
      notes: null,
      why: ["competitor_faster"],
      source: "client",
      ask_pending: false,
    },
  ],
  lessons: [],
  findings: [],
};

const TEAM_ACTIVITY: TeamActivityResponse = {
  period: { kind: "month", start: "2026-11-01", end: "2026-11-30", timezone: "Europe/Warsaw" },
  limit: 20,
  entries: [
    {
      rank: 1,
      user_id: 990901,
      name: "Jakub Szkoleniowy",
      candidates_added: 6,
      added_to_jobs: 14,
      screenings: 9,
      interviews: 3,
      placements: 1,
      calls: 22,
      link_candidates: 2,
      total_actions: 57,
      share_pct: 100,
    },
  ],
  totals: { users: 1, actions: 57 },
} as TeamActivityResponse;

/** Ścieżka API → odpowiedź. Klucz bez query (podstawiony backend dopasowuje po ścieżce). */
/** Moduły Finansów włączone jak na produkcji (przełączniki `{enabled, open}`). */
const MODULE_ON = { enabled: true, open: true };

export const LESSON_SCREENS: Record<string, unknown> = {
  ...SCREENS_FINANCE,
  ...SCREENS_SALES,
  ...SCREENS_CONTRACTS,
  "/api/hr/config": HR_CONFIG,
  "/api/clients/sales-invoices/module": MODULE_ON,
  "/api/finance/costs/module": MODULE_ON,
  "/api/finance/settlements/module": MODULE_ON,
  "/api/finance/periods": [],
  "/api/interview-cycle/question-bank": {
    items: [
      QUESTION(1, "Jak prowadziłeś migrację systemu płatności bez przestoju?", ["Marta Testowa"]),
      QUESTION(2, "Jak raportujesz ryzyko do komitetu sterującego?", ["Marta Testowa", "Piotr Przykładowy"]),
    ],
  },
  "/api/insights/lost-review": LOST_REVIEW,
  "/api/insights/recruitment/team-activity": TEAM_ACTIVITY,
};
