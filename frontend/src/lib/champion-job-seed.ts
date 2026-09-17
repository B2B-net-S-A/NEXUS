/**
 * Profil Championa startuje z pól rekrutacji (M04-B02 + PR 5, program „proces
 * tworzenia rekrutacji dla Delivery Leada").
 *
 * Dwie niezależne rzeczy dzielą jeden moduł, bo obie czytają `job_values` z
 * `GET …/champion-profile` i obie wygasają w ten sam sposób — dopiero gdy
 * Delivery Lead ZMIENI wczytaną wartość, zapis wysyła ją do serwera:
 *
 * 1. **Stack** (profil sprzed 09.2026, patrz historia modułu niżej) — pusty
 *    stack (MUST i NICE) przy niepustych kolumnach `must_skills`/`nice_skills`
 *    jest w edytorze WYPEŁNIANY z kolumn. Reguła jest WSZYSTKO ALBO NIC: obie
 *    listy naraz, bo częściowe wczytanie dawałoby stack, który nie istnieje
 *    nigdzie indziej (ani w profilu, ani w kolumnach).
 * 2. **Podstawowe informacje** (sekcja 1, PR 5) — KAŻDE puste pole osobno
 *    dostaje wartość z odpowiadającej kolumny rekrutacji (`role_name`,
 *    `rate_value`, `work_mode`, `onsite_days_per_week`,
 *    `candidate_location_pref`, `deadline`), niezależnie od pozostałych.
 *    `role_name` bez własnej kolumny (backend sprzed PR 1) spada na tytuł
 *    rekrutacji (`job_title`) — degradacja łagodna, nie błąd.
 *
 * Historia stacku: profil zapisany przed 09.2026 nie ma sekcji `stack` —
 * parser wpisywał wymagania WPROST do kolumn rekrutacji (patrz
 * `champion_view.stack`). Edytor pokazywał więc „Musi mieć · 0”, dok
 * gotowości „Brak — dodaj wymagania”, a scoring w tym samym czasie czytał
 * z kolumn osiem pozycji. Gorzej: dopisanie JEDNEJ technologii do pustej
 * sekcji zapisywało zmieniony stack, a zapis synchronizuje stack do kolumn —
 * osiem wymagań zastępowała jedna.
 *
 * Nic z tego nie jest zapisywane, dopóki Delivery Lead pola nie zmieni: zapis
 * bez zmian wysyła profil BEZ wczytanych-a-nietkniętych kluczy
 * (`championSavePayload`), a serwer bez tych kluczy kolumn/pola nie rusza.
 */

import type { ChampionValidation } from "@/components/ChampionIntake";
import type {
  ChampionBasics,
  ChampionJobValues,
  ChampionProfile,
  ChampionStack,
  StackItem,
} from "@/lib/api";

function namesFromJobValue(value: unknown): StackItem[] {
  if (typeof value !== "string") return [];
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((name) => ({ name }));
}

function isEmptyList(value: unknown): boolean {
  return !Array.isArray(value) || value.length === 0;
}

export interface LegacyStackSeed {
  profile: ChampionProfile;
  /** Stack wczytany z kolumn — `null`, gdy profil ma własny stack albo kolumny są puste. */
  seededStack: ChampionStack | null;
}

export function seedStackFromJobColumns(
  profile: ChampionProfile,
  jobValues: Record<string, unknown> | null | undefined,
): LegacyStackSeed {
  const stack = profile.stack;
  if (!isEmptyList(stack?.must) || !isEmptyList(stack?.nice)) {
    return { profile, seededStack: null };
  }
  const must = namesFromJobValue(jobValues?.must);
  const nice = namesFromJobValue(jobValues?.nice);
  if (must.length === 0 && nice.length === 0) {
    return { profile, seededStack: null };
  }
  const seededStack: ChampionStack = {
    must,
    nice,
    notes: stack?.notes ?? "",
  };
  return { profile: { ...profile, stack: seededStack }, seededStack };
}

function sameItems(a: readonly StackItem[], b: readonly StackItem[]): boolean {
  return a.length === b.length && a.every((item, i) => item.name === b[i]?.name);
}

// ── Sekcja 1 „Podstawowe informacje” — seed per pole ────────────────────────

/**
 * Etykieta trybu pracy w PL. Kolumna `jobs.work_mode` niesie enum
 * (`onsite`/`hybrid`/`remote`); okno w Championie i dopisek „(obecnie: …)”
 * w oknie importu (`ChampionIntake.tsx`) mówią wyłącznie po polsku — surowe
 * „remote” w polskim oknie było zgłoszeniem UAT M04-B06.
 */
export const JOB_WORK_MODE_LABEL: Record<string, string> = {
  remote: "zdalnie",
  hybrid: "hybrydowo",
  onsite: "stacjonarnie",
};

/** Pola sekcji 1, które mają odpowiednik w kolumnach rekrutacji. */
export const SEEDABLE_BASICS = [
  "role_name",
  "rate_value",
  "work_mode",
  "onsite_days_per_week",
  "candidate_location_pref",
  "deadline",
] as const;

export type SeedableBasicsKey = (typeof SEEDABLE_BASICS)[number];

/**
 * Etykiety TYCH SAMYCH pól w `ChampionProfileEditor.tsx` (`<Labeled label=…>`,
 * sekcja 1) — jedno źródło dla notatki „wczytane z rekrutacji”, żeby nazwy pól
 * w komunikacie nigdy nie rozjechały się z formularzem pod nim.
 */
export const SEEDABLE_BASICS_LABEL: Record<SeedableBasicsKey, string> = {
  role_name: "Nazwa roli",
  rate_value: "Maksymalna stawka PLN/h — twardy sufit",
  work_mode: "Tryb pracy",
  onsite_days_per_week: "Dni stacjonarne / tydzień",
  candidate_location_pref: "Lokalizacja biura",
  deadline: "Deadline na kandydatów",
};

function isEmptyBasicsValue(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

export interface BasicsSeed {
  profile: ChampionProfile;
  /** Wartości wczytane do PUSTYCH pól — `null`, gdy nic nie wczytano. */
  seededBasics: Partial<ChampionBasics> | null;
}

/**
 * Wypełnia puste pola sekcji 1 wartościami z kolumn rekrutacji — PER POLE,
 * niezależnie (w odróżnieniu od stacku, który jest wszystko-albo-nic): jedno
 * uzupełnione pole (np. stawka) nie blokuje wczytania drugiego (np. tryb
 * pracy), a wypełnione przez DL pole nigdy nie jest nadpisywane.
 */
export function seedBasicsFromJob(
  profile: ChampionProfile,
  jobValues: ChampionJobValues | Record<string, unknown> | null | undefined,
  jobTitle?: string | null,
): BasicsSeed {
  const basics = profile.basics;
  const values = (jobValues ?? {}) as ChampionJobValues;
  const seeded: Partial<ChampionBasics> = {};

  if (isEmptyBasicsValue(basics.role_name)) {
    // Bez własnej kolumny (backend sprzed PR 1) spadamy na tytuł rekrutacji —
    // degradacja łagodna, nie brak seedu.
    const roleName = values.role_name ?? jobTitle;
    if (typeof roleName === "string" && roleName.trim() !== "") {
      seeded.role_name = roleName;
    }
  }
  if (isEmptyBasicsValue(basics.rate_value) && typeof values.rate_value === "number") {
    seeded.rate_value = values.rate_value;
  }
  if (isEmptyBasicsValue(basics.work_mode) && typeof values.work_mode === "string") {
    // Nieznany enum nie jest seedowany — select w edytorze nie ma dla niego opcji.
    const label = JOB_WORK_MODE_LABEL[values.work_mode];
    if (label) seeded.work_mode = label;
  }
  if (
    isEmptyBasicsValue(basics.onsite_days_per_week) &&
    typeof values.onsite_days_per_week === "number"
  ) {
    seeded.onsite_days_per_week = values.onsite_days_per_week;
  }
  if (
    isEmptyBasicsValue(basics.candidate_location_pref) &&
    typeof values.candidate_location_pref === "string" &&
    values.candidate_location_pref.trim() !== ""
  ) {
    seeded.candidate_location_pref = values.candidate_location_pref;
  }
  if (
    isEmptyBasicsValue(basics.deadline) &&
    typeof values.deadline === "string" &&
    values.deadline.trim() !== ""
  ) {
    seeded.deadline = values.deadline;
  }

  if (Object.keys(seeded).length === 0) {
    return { profile, seededBasics: null };
  }
  return {
    profile: { ...profile, basics: { ...basics, ...seeded } },
    seededBasics: seeded,
  };
}

export interface ChampionJobSeed {
  profile: ChampionProfile;
  seededStack: ChampionStack | null;
  seededBasics: Partial<ChampionBasics> | null;
}

/** Seed stacku (wszystko-albo-nic) + seed sekcji 1 (per pole), w jednym wywołaniu. */
export function seedChampionFromJob(
  profile: ChampionProfile,
  jobValues: ChampionJobValues | Record<string, unknown> | null | undefined,
  jobTitle?: string | null,
): ChampionJobSeed {
  const stackSeed = seedStackFromJobColumns(profile, jobValues);
  const basicsSeed = seedBasicsFromJob(stackSeed.profile, jobValues, jobTitle);
  return {
    profile: basicsSeed.profile,
    seededStack: stackSeed.seededStack,
    seededBasics: basicsSeed.seededBasics,
  };
}

// ── Payload zapisu ───────────────────────────────────────────────────────────

/** Klucze sekcji 1, których wartość w `basics` jest wciąż DOKŁADNIE równa seedowi. */
function stripSeededBasicsKeys(
  basics: ChampionBasics,
  seededBasics: Partial<ChampionBasics> | null,
): ChampionBasics {
  if (!seededBasics) return basics;
  const next: ChampionBasics = { ...basics };
  for (const key of Object.keys(seededBasics) as (keyof ChampionBasics)[]) {
    if (next[key] === seededBasics[key]) {
      delete next[key];
    }
  }
  return next;
}

export interface ChampionSaveSeed {
  seededStack: ChampionStack | null;
  seededBasics: Partial<ChampionBasics> | null;
}

/**
 * Payload zapisu. Nietknięty stack wczytany z kolumn NIE jedzie do serwera —
 * inaczej pierwszy zapis dowolnej sekcji starego profilu zgłaszałby „zmianę
 * stacku” (powiadomienia, przeliczenie dopasowań) dla wymagań, których nikt
 * nie zmienił. Tak samo pola sekcji 1 wczytane z kolumn: wysłanie ich nazad
 * pod niezmienioną wartością byłoby zapisem czegoś, czego DL nigdy nie
 * potwierdził — `user_edit` scala `basics` płytko, więc pominięcie klucza
 * jest bezpieczne (serwer zostawia zapisaną wartość albo pustkę bez zmian).
 */
export function championSavePayload(
  draft: ChampionProfile,
  seed: ChampionSaveSeed,
): ChampionProfile | Omit<ChampionProfile, "stack"> {
  const withBasics: ChampionProfile = {
    ...draft,
    basics: stripSeededBasicsKeys(draft.basics, seed.seededBasics),
  };
  const { seededStack } = seed;
  if (
    seededStack &&
    sameItems(withBasics.stack.must, seededStack.must) &&
    sameItems(withBasics.stack.nice, seededStack.nice) &&
    withBasics.stack.notes === seededStack.notes
  ) {
    const { stack: _untouched, ...rest } = withBasics;
    return rest;
  }
  return withBasics;
}

/**
 * Konflikt „profil i pola rekrutacji mają różne wymagania” opisuje ZAPISANY
 * pusty stack. Gdy edytor pokazuje stack wczytany z tych kolumn, ten komunikat
 * zaprzeczałby liście stojącej pod nim — pomijamy go.
 */
export function withoutSeededStackConflict(
  validation: ChampionValidation | undefined,
  seededStack: ChampionStack | null,
): ChampionValidation | undefined {
  if (!validation || !seededStack) return validation;
  const issues = validation.issues.filter(
    (issue) =>
      !(
        issue.code === "skill_column_conflict" &&
        issue.path.startsWith("stack.")
      ),
  );
  if (issues.length === validation.issues.length) return validation;
  const blocked = Array.from(
    new Set(issues.flatMap((issue) => issue.blocked_operations)),
  );
  return { ...validation, issues, blocked_operations: blocked };
}
