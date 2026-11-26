/**
 * Insights → „Przegrane” (decyzje Artura 25.11.2026): przegląd przegranych
 * rekrutacji na comiesięczne spotkanie z Delivery Leadami.
 *
 * Lustro słowników z `backend/app/services/lost_review.py` (`WHY`, `SOURCES`,
 * `STAGES`). Reguła: `docs/claude/finanse-insights/przegrane-przeglad-z-dl.md`.
 */

import { api } from "@/lib/api";
import type { InsightsPeriodParams } from "@/lib/insights-api";

export type LostWhyKey =
  | "competitor_faster"
  | "competitor_cheaper"
  | "weaker_profile"
  | "client_had_own"
  | "candidate_withdrew"
  | "too_few_cvs";

export type LostWhySource = "client" | "ours" | "unknown";
export type LostStage = "no_cv" | "cv_only" | "interview" | "acceptance";
export type LessonScope = "job" | "client" | "all";

export const LOST_WHY: readonly { key: LostWhyKey; label: string }[] = [
  { key: "competitor_faster", label: "Konkurent był szybszy" },
  { key: "competitor_cheaper", label: "Konkurent tańszy" },
  { key: "weaker_profile", label: "Słabszy profil od wybranego" },
  { key: "client_had_own", label: "Klient miał już swoją osobę" },
  { key: "candidate_withdrew", label: "Nasz kandydat się wycofał" },
  { key: "too_few_cvs", label: "Za mało CV / brak ludzi" },
];
export const LOST_WHY_MAX = 2;

export const LOST_WHY_SOURCES: readonly { key: LostWhySource; label: string }[] = [
  { key: "client", label: "Klient powiedział" },
  { key: "ours", label: "Nasza ocena" },
  { key: "unknown", label: "Nie wiemy — zapytam klienta" },
];

export const LOST_STAGES: readonly { key: LostStage; label: string; hint: string }[] = [
  { key: "no_cv", label: "Bez CV", hint: "nie wysłaliśmy nikogo" },
  { key: "cv_only", label: "CV bez rozmowy", hint: "klient nikogo nie zaprosił" },
  { key: "interview", label: "Po rozmowie", hint: "był u klienta, wybrali innego" },
  { key: "acceptance", label: "Po akceptacji", hint: "mieliśmy „tak”, skończyło się" },
];

export const LESSON_SCOPES: readonly { key: LessonScope; label: string }[] = [
  { key: "client", label: "ten klient" },
  { key: "job", label: "ta rekrutacja" },
  { key: "all", label: "wszyscy klienci" },
];

export function lostWhyLabel(key: string): string {
  return LOST_WHY.find((w) => w.key === key)?.label ?? key;
}

/** Klik w powód: dodaje albo zdejmuje; trzeci zastępuje najstarszy. */
export function toggleLostWhy(current: readonly LostWhyKey[], key: LostWhyKey): LostWhyKey[] {
  if (current.includes(key)) return current.filter((k) => k !== key);
  return [...current, key].slice(-LOST_WHY_MAX);
}

export interface LostReviewCount {
  label: string;
  count: number;
}

export interface LostReviewSide {
  count: number;
  first_cv_days: number | null;
  cvs: number | null;
  interview_share: number | null;
}

export interface LostReviewLesson {
  id: number;
  scope: LessonScope;
  client_id: number | null;
  /** Nazwa klienta wniosku — także spoza okresu (lista „Wnioski ze spotkań”). */
  client_name?: string | null;
  job_id: number | null;
  text: string;
  created_at: string | null;
  effect?: {
    before: { won: number; lost: number; hit_ratio: number | null };
    after: { won: number; lost: number; hit_ratio: number | null };
  } | null;
}

export interface LostReviewClient {
  client_id: number;
  name: string;
  won: number;
  lost: number;
  idle: number;
  hit_ratio: number | null;
  stages: Record<LostStage, number>;
  pattern: string | null;
  verdicts: LostReviewCount[];
  why: LostReviewCount[];
  lessons: LostReviewLesson[];
}

export interface LostReviewJob {
  job_id: number;
  title: string;
  client_id: number;
  client_name: string;
  dl_id: number | null;
  dl_name: string | null;
  outcome: "competitor" | "idle";
  stage: LostStage;
  closed_at: string;
  days_open: number | null;
  days_first_cv: number | null;
  cvs: number;
  interviews: number;
  client_verdicts: string[];
  notes: string | null;
  why: LostWhyKey[];
  source: LostWhySource | null;
  ask_pending: boolean;
}

export interface LostReviewTrendMonth {
  month: string;
  label: string;
  won: number;
  lost: number;
  hit_ratio: number | null;
}

/** DL z zamknięciami okresu (lista filtra na górze); `id` 0 = rekrutacje bez DL. */
export interface LostReviewDl {
  id: number;
  name: string;
  won: number;
  lost: number;
}

/** Filtr DL z góry ekranu: `null` = cała firma, 0 = rekrutacje bez DL. */
export type LostReviewDlFilter = number | null;
export const LOST_NO_DL = 0;

export interface LostReviewResponse {
  period: { kind: string; start: string; end: string };
  period_label: string;
  since: string;
  dl_id: LostReviewDlFilter;
  dls: LostReviewDl[];
  counts: { won: number; lost: number; competitor: number; idle: number };
  hit_ratio: number | null;
  known: number;
  why_filled: number;
  stages: Record<LostStage, number>;
  compare: { won: LostReviewSide; lost: LostReviewSide };
  trend: LostReviewTrendMonth[];
  why_counts: (LostReviewCount & { key: LostWhyKey })[];
  source_counts: Record<LostWhySource, number>;
  client_verdicts: LostReviewCount[];
  clients: LostReviewClient[];
  jobs: LostReviewJob[];
  lessons: LostReviewLesson[];
  findings: string[];
}

export interface LostReviewAiSummary {
  conclusions: string[];
  advice: { for: string; text: string }[];
  questions: string[];
  model: string;
  generated_at: string;
  cached: boolean;
}

function periodQuery(p: InsightsPeriodParams, dl: LostReviewDlFilter = null): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (dl !== null) q.dl_id = dl;
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

export const lostReviewKeys = {
  all: ["insights", "lost-review"] as const,
  review: (p: InsightsPeriodParams, dl: LostReviewDlFilter = null) => ["insights", "lost-review", p, dl] as const,
  ai: (p: InsightsPeriodParams) => ["insights", "lost-review", "ai", p] as const,
  clientRules: (clientId: number) => ["insights", "lost-review", "client-rules", clientId] as const,
};

export const lostReviewApi = {
  get: (p: InsightsPeriodParams, dl: LostReviewDlFilter = null) =>
    api
      .get<LostReviewResponse>("/api/insights/lost-review", { params: periodQuery(p, dl) })
      .then((r) => r.data),
  aiSummary: (p: InsightsPeriodParams, refresh = false, dl: LostReviewDlFilter = null) =>
    api
      .post<LostReviewAiSummary>("/api/insights/lost-review/ai-summary", null, {
        params: { ...periodQuery(p, dl), ...(refresh ? { refresh: true } : {}) },
      })
      .then((r) => r.data),
  saveWhy: (jobId: number, body: { why: LostWhyKey[]; source: LostWhySource | null }) =>
    api
      .put<{ job_id: number; why: LostWhyKey[]; source: LostWhySource | null }>(
        `/api/insights/lost-review/jobs/${jobId}/why`,
        body,
      )
      .then((r) => r.data),
  clientQuestion: (jobId: number) =>
    api
      .get<{ subject: string; body: string }>(
        `/api/insights/lost-review/jobs/${jobId}/client-question`,
      )
      .then((r) => r.data),
  addLesson: (body: { scope: LessonScope; text: string; job_id?: number | null; client_id?: number | null }) =>
    api.post<LostReviewLesson>("/api/insights/lost-review/lessons", body).then((r) => r.data),
  archiveLesson: (id: number) => api.delete(`/api/insights/lost-review/lessons/${id}`),
  clientRules: (clientId: number) =>
    api
      .get<{ rules: LostReviewLesson[] }>(`/api/insights/lost-review/client-rules/${clientId}`)
      .then((r) => r.data.rules),
};

/** Liczba po polsku: przecinek dziesiętny, „—” dla braku. */
export function plNumber(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("pl-PL", { maximumFractionDigits: digits });
}
