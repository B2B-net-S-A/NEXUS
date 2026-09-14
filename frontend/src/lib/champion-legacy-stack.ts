/**
 * Stack Championa na profilach sprzed przebudowy (M04-B02).
 *
 * Profil zapisany przed 09.2026 nie ma sekcji `stack` — parser wpisywał
 * wymagania WPROST do kolumn rekrutacji (`jobs.must_skills`/`nice_skills`,
 * patrz `champion_view.stack`). Edytor pokazywał więc „Musi mieć · 0”, dok
 * gotowości „Brak — dodaj wymagania”, a scoring w tym samym czasie czytał
 * z kolumn osiem pozycji. Gorzej: dopisanie JEDNEJ technologii do pustej
 * sekcji zapisywało zmieniony stack, a zapis synchronizuje stack do kolumn —
 * osiem wymagań zastępowała jedna.
 *
 * Dlatego pusty stack (MUST i NICE) przy niepustych kolumnach jest w edytorze
 * WYPEŁNIANY z kolumn (`job_values` z `GET …/champion-profile` — te same
 * efektywne nazwy, z którymi porównuje walidacja). Nic nie jest zapisywane,
 * dopóki Delivery Lead stacku nie zmieni: zapis bez zmian wysyła profil BEZ
 * sekcji `stack`, a serwer bez tej sekcji kolumn nie rusza.
 */

import type { ChampionValidation } from "@/components/ChampionIntake";
import type { ChampionProfile, ChampionStack, StackItem } from "@/lib/api";

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

/**
 * Payload zapisu. Nietknięty stack wczytany z kolumn NIE jedzie do serwera —
 * inaczej pierwszy zapis dowolnej sekcji starego profilu zgłaszałby „zmianę
 * stacku” (powiadomienia, przeliczenie dopasowań) dla wymagań, których nikt nie
 * zmienił.
 */
export function championSavePayload(
  draft: ChampionProfile,
  seededStack: ChampionStack | null,
): ChampionProfile | Omit<ChampionProfile, "stack"> {
  if (
    seededStack &&
    sameItems(draft.stack.must, seededStack.must) &&
    sameItems(draft.stack.nice, seededStack.nice) &&
    draft.stack.notes === seededStack.notes
  ) {
    const { stack: _untouched, ...rest } = draft;
    return rest;
  }
  return draft;
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
