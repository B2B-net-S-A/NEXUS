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
  "contact",
  "action",
  "view",
] as const;
export type WorkRhythmKind = (typeof WORK_RHYTHM_KINDS)[number];

export const WORK_RHYTHM_KIND_LABELS: Record<WorkRhythmKind, string> = {
  screening: "Screening (karta, fakty z rozmowy, formularz)",
  client_step: "Rozmowa u klienta umówiona, feedback, prep",
  cv: "Wygenerowane CV",
  note: "Notatka, dodany kandydat, finalizacja CV",
  contact: "Próba kontaktu („nie odbiera”)",
  action: "Ruch karty, wysłany mail, QC CV, inny zapis",
  view: "Podgląd CV lub dokumentu",
};

export interface WorkRhythmRules {
  weights: Record<WorkRhythmKind, number>;
  /** Progi poziomu godziny: od ilu punktów robocza, intensywna, bardzo intensywna. */
  hour_levels: [number, number, number];
  work_hour_min_points: number;
  min_work_hours: number;
  norm_day_points: number;
  level_high: number;
  level_mid: number;
  diag_intensity: number;
  diag_results_pct: number;
  /** Ochrona przed nabijaniem (29.10.2026); limit 0 = bez limitu. */
  auto_cv_points: number;
  screening_per_candidate_day: number;
  repeats_per_hour: number;
  views_per_hour: number;
  bulk_per_minute: number;
  stage_return_points: number;
  contacts_per_day: number;
  thin_hour_candidates: number;
  /** Tyle minut bez akcji i bez prepa to przerwa, nie praca. */
  break_minutes: number;
}

/** Powody, dla których akcja nie dała punktów — lustro `SKIP_REASONS` z serwera. */
export type WorkRhythmSkipReason =
  | "automat"
  | "powtorka"
  | "limit_podgladow"
  | "masowa"
  | "powrot"
  | "limit_kontaktu";

export const WORK_RHYTHM_SKIP_LABELS: Record<WorkRhythmSkipReason, string> = {
  automat: "CV wygenerował automat",
  powtorka: "ponowny zapis albo otwarcie tego samego",
  limit_podgladow: "ponad limit podglądów w godzinie",
  masowa: "masowa akcja liczy się raz",
  powrot: "karta wróciła na ten sam etap",
  limit_kontaktu: "ponad dzienny limit prób kontaktu",
};

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
  /** Godzina z samych drobnych akcji przy jednym kandydacie — nie jest godziną pracy. */
  thin: boolean[];
  /** Punkty, które odpadły z ochrony przed nabijaniem, według powodu. */
  skipped: Partial<Record<WorkRhythmSkipReason, number>>;
  first: string | null;
  last: string | null;
  work_hours: number | null;
  /** Czas pracy dnia w godzinach; `null` = dzień nie liczy się (urlop, przed kontem). */
  work_time: number | null;
  day_points: number;
  /** `null` = dzień nie liczy się (urlop, przed startem). */
  index: number | null;
}

export type WorkRhythmLevel = "high" | "mid" | "low";
/** Podpowiedź: najpierw minimum 8 h, potem intensywność i wyniki (29.10.2026). */
export type WorkRhythmDiagnosis = "model" | "quality" | "idle" | "short_good" | "more_work";

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
  /** Średni czas pracy dziennie (h): odcinki z akcjami i prepami, 30 min ciszy = przerwa. */
  avg_work_time: number | null;
  /** Dni z pełnym minimum godzin (pół dnia urlopu = połowa minimum). */
  full_days: number;
  /** Dni z policzonym czasem pracy (mianownik dla `full_days`). */
  timed_days: number;
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

export interface WorkRhythmDayEvent {
  time: string;
  hour: number;
  kind: WorkRhythmKind;
  label: string;
  candidate: string | null;
  points: number;
  weight: number;
  reason: WorkRhythmSkipReason | null;
}

export interface WorkRhythmDayDetail {
  user_id: number;
  name: string;
  date: string;
  points: number[];
  meetings: boolean[];
  thin: boolean[];
  skipped: Partial<Record<WorkRhythmSkipReason, number>>;
  work_time: number;
  /** Odcinki pracy [od, do] (HH:MM); między nimi przerwy. */
  spans: [string, string][];
  events: WorkRhythmDayEvent[];
}

export const workRhythmQueryKeys = {
  all: ["insights", "work-rhythm"] as const,
  window: (from: string | null, to: string | null) =>
    ["insights", "work-rhythm", from, to] as const,
  day: (userId: number, day: string) => ["insights", "work-rhythm", "day", userId, day] as const,
};

export const workRhythmApi = {
  get: async (params: { date_from?: string; date_to?: string } = {}) =>
    (await api.get<WorkRhythmResponse>("/api/insights/work-rhythm", { params })).data,
  day: async (userId: number, day: string) =>
    (
      await api.get<WorkRhythmDayDetail>("/api/insights/work-rhythm/day", {
        params: { user_id: userId, day },
      })
    ).data,
  saveRules: async (rules: WorkRhythmRules) =>
    (
      await api.put<{ rules: WorkRhythmRules; can_edit: boolean }>(
        "/api/insights/work-rhythm/rules",
        rules,
      )
    ).data,
};
