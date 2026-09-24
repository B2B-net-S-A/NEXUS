/**
 * Panel „Praktykanci” (0373) — czyste reguły prezentacji dla Head of
 * Recruitment: stan osoby, zdania podsumowań, starczalność puli.
 */

import type { TraineeOverviewRow, TraineePool, TraineeRules } from "@/lib/api/trainee";

export type TraineeState =
  | "decision"
  | "check"
  | "below_norm"
  | "ok"
  | "not_started"
  | "ended";

export const TRAINEE_STATE_LABEL: Record<TraineeState, string> = {
  decision: "Do decyzji",
  check: "Do sprawdzenia",
  below_norm: "Poniżej normy",
  ok: "W normie",
  not_started: "Bez listy",
  ended: "Program zakończony",
};

/** Poniżej 80% zaliczonych dni = poniżej normy (70 pozycji dziennie). */
export const DAYS_COMPLETED_NORM = 0.8;

export function traineeState(row: TraineeOverviewRow): TraineeState {
  const program = row.program;
  if (!program || program.status === "ended" || program.status === "finished") {
    return program ? "ended" : "not_started";
  }
  if (program.decision_due) return "decision";
  if (row.flag_low_answer || row.quality.issues >= 2) return "check";
  if (row.days_with_list === 0) return "not_started";
  if (row.days_completed / row.days_with_list < DAYS_COMPLETED_NORM) return "below_norm";
  return "ok";
}

/** 1 uwaga · 2 uwagi · 5 uwag. */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const tens = n % 100;
  const units = n % 10;
  if (units >= 2 && units <= 4 && (tens < 12 || tens > 14)) return few;
  return many;
}

export function qualityLabel(quality: TraineeOverviewRow["quality"]): string {
  if (quality.checked === 0) return "nie sprawdzano";
  return `${quality.checked} sprawdz., ${quality.issues} ${plural(quality.issues, "uwaga", "uwagi", "uwag")}`;
}

export function pctLabel(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value)}%`;
}

export function daysCompletedLabel(row: TraineeOverviewRow): { main: string; pct: string | null } {
  if (row.days_with_list === 0) return { main: "—", pct: null };
  return {
    main: `${row.days_completed} z ${row.days_with_list}`,
    pct: `(${Math.round((row.days_completed / row.days_with_list) * 100)}%)`,
  };
}

/** „Zaliczone 37 z 40 dni · 27 rozmów dziennie · 91% pełnych profili · …”. */
export function decisionSummary(row: TraineeOverviewRow): string {
  const parts: string[] = [];
  if (row.days_with_list > 0) {
    parts.push(`Zaliczone ${row.days_completed} z ${row.days_with_list} dni`);
  }
  if (row.calls_per_day != null) parts.push(`${Math.round(row.calls_per_day)} rozmów dziennie`);
  if (row.complete_profiles_pct != null) {
    parts.push(`${Math.round(row.complete_profiles_pct)}% pełnych profili`);
  }
  parts.push(
    `${row.handed_over} ${plural(row.handed_over, "przekazana osoba", "przekazane", "przekazanych")}, ${row.handed_in_process} ${plural(row.handed_in_process, "weszła", "weszły", "weszło")} do procesu`,
  );
  parts.push(
    row.quality.checked === 0
      ? "próbka jakości niesprawdzona"
      : row.quality.issues === 0
        ? "próbka jakości bez uwag"
        : `próbka jakości: ${row.quality.issues} ${plural(row.quality.issues, "uwaga", "uwagi", "uwag")}`,
  );
  return parts.join(" · ");
}

/**
 * Zdanie pod wierszem osoby z niskim odsetkiem odebranych. Liczba sama nie
 * mówi, co z nią zrobić — zdanie mówi.
 */
export function lowAnswerNote(row: TraineeOverviewRow, teamPct: number | null): string {
  const team = teamPct == null ? "" : ` przy średniej ${Math.round(teamPct)}%`;
  return `${row.name}: odebrane ${pctLabel(row.answered_pct)}${team} — większość pozycji to „Nie odbiera”. Sprawdź próbkę jakości, zanim uznasz dni za zaliczone.`;
}

/**
 * Na ile dni roboczych starczy pula przy obecnych praktykantach (aktywne
 * programy × dzienna lista). `null` = nikt dziś nie dzwoni.
 */
export function poolWorkdays(
  pool: TraineePool | null,
  rows: readonly TraineeOverviewRow[],
): number | null {
  if (!pool) return null;
  const active = rows.filter((r) => r.is_active && traineeState(r) !== "ended" && r.program);
  const perDay = active.reduce((sum, r) => sum + (r.program?.daily_list_size ?? 0), 0);
  if (perDay <= 0) return null;
  return Math.floor(pool.size / perDay);
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

// ── Reguły listy ─────────────────────────────────────────────────────────────

export const NUMBER_RULE_KEYS = [
  "min_fits",
  "window_months",
  "rate_stale_months",
  "verified_recently_days",
  "process_active_days",
  "my_people_contact_days",
  "trainee_recall_days",
] as const satisfies ReadonlyArray<keyof TraineeRules>;

export const BOOL_RULE_KEYS = [
  "missing_rate",
  "missing_availability",
  "missing_work_mode",
  "missing_consents",
  "missing_b2b",
  "missing_work_time",
] as const satisfies ReadonlyArray<keyof TraineeRules>;

export type NumberRuleKey = (typeof NUMBER_RULE_KEYS)[number];
export type BoolRuleKey = (typeof BOOL_RULE_KEYS)[number];

/** Pola liczbowe jako tekst — puste pole w trakcie pisania to nie zero. */
export type TraineeRulesDraft = Record<NumberRuleKey, string> & Record<BoolRuleKey, boolean>;

/** Najmniejsza sensowna wartość: „pasuje do 0 rekrutacji” wpuściłoby całą bazę. */
const RULE_MIN: Record<NumberRuleKey, number> = {
  min_fits: 1,
  window_months: 1,
  rate_stale_months: 1,
  verified_recently_days: 0,
  process_active_days: 0,
  my_people_contact_days: 0,
  trainee_recall_days: 0,
};

export function draftFromRules(rules: TraineeRules): TraineeRulesDraft {
  const draft = {} as TraineeRulesDraft;
  for (const key of NUMBER_RULE_KEYS) draft[key] = String(rules[key]);
  for (const key of BOOL_RULE_KEYS) draft[key] = rules[key];
  return draft;
}

export function rulesFromDraft(draft: TraineeRulesDraft): {
  rules: TraineeRules | null;
  errors: Partial<Record<NumberRuleKey, string>>;
} {
  const errors: Partial<Record<NumberRuleKey, string>> = {};
  const rules = {} as TraineeRules;
  for (const key of NUMBER_RULE_KEYS) {
    const raw = draft[key].trim();
    const value = Number(raw);
    if (raw === "" || !/^\d+$/.test(raw) || value < RULE_MIN[key]) {
      errors[key] = RULE_MIN[key] > 0 ? `Co najmniej ${RULE_MIN[key]}.` : "Liczba całkowita ≥ 0.";
      continue;
    }
    rules[key] = value;
  }
  for (const key of BOOL_RULE_KEYS) rules[key] = draft[key];
  return { rules: Object.keys(errors).length ? null : rules, errors };
}
