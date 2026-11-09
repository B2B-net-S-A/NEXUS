/**
 * „Kto już to robił” — wyszukiwanie po celu projektu i obowiązkach (09.11.2026).
 * Backend: `backend/app/api/duty_search.py`; reguła
 * `docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md`.
 */
import { api } from "@/lib/api";

export type DutyTier = "zrobil_to" | "bardzo_blisko" | "ma_klocki" | "brak";
export type DutyCapState = "tak" | "czesciowo" | "brak";
export type DutyRunState = "queued" | "running" | "complete" | "failed";

export interface DutyCapability {
  name: string;
  weight: number;
  hint: string;
}

export interface DutyEvidence {
  quote: string;
  where: string;
  meaning: string;
}

export interface DutyResult {
  candidate_id: number;
  name: string;
  position: string;
  years_it: number | null;
  tier: DutyTier;
  confidence: number | null;
  /** Dzisiejszy kanoniczny „Dop.”; brak = poza top 50 zwykłego wyszukiwania. */
  fit_score: number | null;
  from_goal_only: boolean;
  capabilities: Record<string, DutyCapState>;
  evidence: DutyEvidence[];
  gap: string;
  question: string;
  /** `no_cv` / `model` / `parse` — AI nie oceniło tej osoby. */
  error: string | null;
  feedback: "up" | "down" | null;
}

export interface DutyUsage {
  used_today: number;
  daily_limit: number;
}

export interface DutyRun {
  run_id: string;
  state: DutyRunState;
  error_code: string | null;
  job_id: number | null;
  client_id: number | null;
  title: string | null;
  goal: string;
  created_at: string | null;
  completed_at: string | null;
  plan: {
    summary: string;
    capabilities: DutyCapability[];
    signals: { signal: string; why: string }[];
    anti: string[];
  };
  stats: {
    judged: number | null;
    seconds: number | null;
    tiers: Partial<Record<DutyTier, number>>;
    plan_ok: boolean | null;
    canonical_degraded: boolean | null;
    judge_errors: number | null;
  };
  results: DutyResult[];
  usage: DutyUsage;
}

export interface DutyJobLatest {
  has_duties: boolean;
  duties: string;
  title: string;
  run: DutyRun | null;
  usage: DutyUsage;
}

export interface StartDutySearch {
  job_id?: number;
  client_id?: number;
  title?: string;
  goal?: string;
}

export const dutySearchKeys = {
  run: (runId: string) => ["duty-search", "run", runId] as const,
  jobLatest: (jobId: number) => ["duty-search", "job", jobId] as const,
};

export function dutyRunIsActive(state: DutyRunState | undefined): boolean {
  return state === "queued" || state === "running";
}

/** Kod przyczyny z serwera → zdanie dla rekrutera. */
export function dutyFailureMessage(code: string | null): string {
  switch (code) {
    case "judge_unavailable":
      return "AI nie odpowiedziało przy ocenie CV. Spróbuj ponownie za kilka minut.";
    case "retrieval_unavailable":
      return "Wyszukiwarka w bazie nie odpowiada (indeks wektorowy). Spróbuj ponownie za kilka minut.";
    case "abandoned":
      return "Wyszukiwanie przerwało się kilka razy (np. przy wdrożeniu). Uruchom je ponownie.";
    default:
      return "Wyszukiwanie nie powiodło się. Uruchom je ponownie; jeśli to się powtórzy, zgłoś to.";
  }
}

export const dutySearchApi = {
  start: (body: StartDutySearch) =>
    api
      .post<{ run_id: string; state: DutyRunState; usage: DutyUsage }>("/api/duty-search/runs", body)
      .then((r) => r.data),
  run: (runId: string, signal?: AbortSignal) =>
    api.get<DutyRun>(`/api/duty-search/runs/${encodeURIComponent(runId)}`, { signal }).then((r) => r.data),
  jobLatest: (jobId: number, signal?: AbortSignal) =>
    api.get<DutyJobLatest>(`/api/jobs/${jobId}/duty-search/latest`, { signal }).then((r) => r.data),
  feedback: (runId: string, candidateId: number, vote: "up" | "down" | null) =>
    api
      .put<{ candidate_id: number; feedback: "up" | "down" | null }>(
        `/api/duty-search/runs/${encodeURIComponent(runId)}/results/${candidateId}/feedback`,
        { vote },
      )
      .then((r) => r.data),
};
