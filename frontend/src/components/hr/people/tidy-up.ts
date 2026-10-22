/**
 * „Porządki” w katalogu „Ludzi” (22.10.2026): jeden przycisk zamiast żółtego
 * paska „Do wyrównania” nad katalogiem i panelu „Do uporządkowania” obok
 * Struktury. Czyste funkcje — bramki, liczba i kartoteki „do uzupełnienia”.
 */

import { isFullPerson, type HrConfig, type Person } from "@/lib/api/hr";

import type { PendingPerson } from "./AccountMismatchesPanel";

/** Schemat i sekcja „Struktura”: Kadry i admin przy otwartym module (jak dawna zakładka). */
export function canSeeStructure(config: HrConfig): boolean {
  return config.open_modules.people && (config.me.people_admin || config.me.is_admin);
}

/** Rozjazdy kartoteka ↔ konto: admin, Finanse i Kadry (19.10.2026). */
export function canSeeAccounts(config: HrConfig): boolean {
  return config.me.people_admin || config.me.payroll || config.me.is_admin;
}

/** Kartoteka „do uzupełnienia” (z konta): forma albo przełożony — bez zdradzania formy. */
export function needsCompletion(person: Person): boolean {
  return isFullPerson(person) && (person.employment_type_pending || Boolean(person.manager_pending));
}

/** Kto ma kartotekę „do uzupełnienia” — do listy rozjazdów (bez zdradzania formy). */
export function pendingPeople(rows: readonly Person[]): PendingPerson[] {
  return rows.filter(needsCompletion).map((row) => {
    const full = isFullPerson(row) ? row : null;
    const what = [
      full?.employment_type_pending ? "forma" : null,
      full?.manager_pending ? "koordynator" : null,
    ].filter(Boolean);
    return { user_id: row.user_id, name: row.name, what: what.join(" i ") };
  });
}

/** Stan jednej części „Porządków”: poza bramką, w drodze, awaria albo liczba. */
export type TidyPart =
  | { status: "off" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ok"; count: number };

/**
 * Co pokazuje przycisk: `hidden` — nic do zrobienia (albo żadna część osoby
 * nie dotyczy, albo liczba jeszcze w drodze), `unknown` — któryś odczyt padł
 * (bez liczby, nigdy „0”), `count` — suma części.
 */
export type TidyTotal = { kind: "hidden" } | { kind: "unknown" } | { kind: "count"; count: number };

export function tidyTotal(parts: readonly TidyPart[]): TidyTotal {
  const active = parts.filter((part) => part.status !== "off");
  if (active.length === 0) return { kind: "hidden" };
  if (active.some((part) => part.status === "error")) return { kind: "unknown" };
  if (active.some((part) => part.status === "loading")) return { kind: "hidden" };
  const count = active.reduce((sum, part) => sum + (part.status === "ok" ? part.count : 0), 0);
  return count > 0 ? { kind: "count", count } : { kind: "hidden" };
}

/** Stan części z zapytania react-query (bez zgadywania liczby przy awarii). */
export function tidyPart<T>(
  enabled: boolean,
  query: { isError: boolean; data: T | undefined },
  count: (data: T) => number,
): TidyPart {
  if (!enabled) return { status: "off" };
  if (query.isError) return { status: "error" };
  if (query.data === undefined) return { status: "loading" };
  return { status: "ok", count: count(query.data) };
}
