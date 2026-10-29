import api from "@/lib/api";

/**
 * Klient Insights → „Rytm dnia” (`/api/insights/work-rhythm`, 28.10.2026).
 * Reguły liczenia są po stronie serwera (`services/work_rhythm.py`); front
 * tylko je pokazuje i — dla Head of Recruitment i admina — zapisuje.
 */

export const WORK_RHYTHM_KINDS = [
  "screening",
  "client_step",
  "cv",
  "note",
  "action",
  "view",
] as const;
export type WorkRhythmKind = (typeof WORK_RHYTHM_KINDS)[number];

export const WORK_RHYTHM_KIND_LABELS: Record<WorkRhythmKind, string> = {
  screening: "Screening (karta, fakty z rozmowy, formularz)",
  client_step: "Rozmowa u klienta umówiona, feedback, prep",
  cv: "Wygenerowane CV",
  note: "Notatka (także „nie odbiera”), dodany kandydat, finalizacja CV",
  action: "Ruch karty, wysłany mail, QC CV, inny zapis",
  view: "Podgląd CV lub dokumentu",
};

export interface WorkRhythmRules {
  weights: Record<WorkRhythmKind, number>;
  /** Progi poziomu godziny: od ilu punktów robocza, intensywna, bardzo intensywna. */
  hour_levels: [number, number, number];
  work_hour_min_points: number;
  norm_work_hours: number;
  norm_day_points: number;
  level_high: number;
  level_mid: number;
  diag_intensity: number;
  diag_results_pct: number;
}

export interface WorkRhythmDay {
  date: string;
  /** Dzień przed założeniem konta — nie liczy się do wskaźnika. */
  before_start: boolean;
  /** Dzisiejszy, jeszcze trwający dzień — widać go, ale nie liczy się do okresu. */
  in_progress: boolean;
  /** Część dnia na urlopie: 0, 0,5 albo 1. */
  leave: number;
  points: number[];
  /** 0 brak · 1 lekka · 2 robocza · 3 intensywna · 4 bardzo intensywna. */
  levels: number[];
  counts: number[];
  meetings: boolean[];
  first: string | null;
  last: string | null;
  work_hours: number | null;
  day_points: number;
  /** `null` = dzień nie liczy się (urlop, przed startem). */
  index: number | null;
}

export type WorkRhythmLevel = "high" | "mid" | "low";
export type WorkRhythmDiagnosis = "model" | "quality" | "more_volume" | "more_work";

export interface WorkRhythmPerson {
  user_id: number;
  name: string;
  days: WorkRhythmDay[];
  index: number | null;
  level: WorkRhythmLevel | null;
  worked_days: number;
  leave_days: number;
  days_before_start: number;
  avg_work_hours: number | null;
  median_points: number | null;
  /** Tylko dla widzów zakładki (admin, Head of Recruitment). */
  cv_sent?: number;
  cv_per_day?: number | null;
  results_pct?: number | null;
  diagnosis?: WorkRhythmDiagnosis | null;
}

export interface WorkRhythmResponse {
  from: string;
  to: string;
  days: string[];
  rules: WorkRhythmRules;
  people: WorkRhythmPerson[];
  team_cv_per_day_median: number | null;
  can_edit_rules: boolean;
  with_results: boolean;
}

/** Godziny na osi (7–19) — lustro `HOURS` z serwera. */
export const WORK_RHYTHM_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19];

export const workRhythmQueryKeys = {
  all: ["insights", "work-rhythm"] as const,
  window: (from: string | null, to: string | null) =>
    ["insights", "work-rhythm", from, to] as const,
};

export const workRhythmApi = {
  get: async (params: { date_from?: string; date_to?: string } = {}) =>
    (await api.get<WorkRhythmResponse>("/api/insights/work-rhythm", { params })).data,
  saveRules: async (rules: WorkRhythmRules) =>
    (
      await api.put<{ rules: WorkRhythmRules; can_edit: boolean }>(
        "/api/insights/work-rhythm/rules",
        rules,
      )
    ).data,
};
