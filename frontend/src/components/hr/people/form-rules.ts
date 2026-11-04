// Reguły kartoteki zależne od formy współpracy (etap 2, D6, D8, D9) — czyste
// funkcje bez renderu (`__tests__/form-rules.test.ts`).
//
// Serwer pilnuje tego samego (`app/services/hr/people.py`, `leave_policy`):
// tu tylko podpowiedzi w oknach Kadr, zanim zapis wróci z 422.

import type { EmploymentType } from "@/lib/api/hr";

/** Ile dni przed końcem zwolnienia ze składek Płace dostają przypomnienie. */
export const STUDENT_REMINDER_LEAD_DAYS = 30;

const DAY_MS = 24 * 60 * 60 * 1000;

/** Dzień kalendarza ± dni — arytmetyka na samej dacie (UTC tylko jako licznik dni). */
function shiftIso(iso: string, days: number): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const moved = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) + days * DAY_MS,
  );
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${moved.getUTCFullYear()}-${pad(moved.getUTCMonth() + 1)}-${pad(moved.getUTCDate())}`;
}

/** „2027-07-01” → „01.07.2027”. */
export function dayLabel(iso: string): string {
  const [year, month, day] = iso.split("-");
  return `${day}.${month}.${year}`;
}

/** Dzień, od którego Płace naliczają składki (dzień po końcu zwolnienia). */
export function contributionsStart(exemptUntil: string | null | undefined): string | null {
  return exemptUntil ? shiftIso(exemptUntil, 1) : null;
}

/** Dzień przypomnienia dla Płac i Kadr (30 dni przed końcem zwolnienia). */
export function contributionsReminder(exemptUntil: string | null | undefined): string | null {
  return exemptUntil ? shiftIso(exemptUntil, -STUDENT_REMINDER_LEAD_DAYS) : null;
}

/** Plakietka przy osobie: „składki od 07.2027” (Struktura, Mój zespół). */
export function contributionsBadge(from: string | null | undefined): string | null {
  if (!from) return null;
  const [year, month] = from.split("-");
  return year && month ? `składki od ${month}.${year}` : null;
}

/**
 * Wymiar urlopu na umowie o pracę (art. 154 KP): 20 dni poniżej 10 lat stażu,
 * 26 od 10 lat. Lustro `leave_policy.statutory_entitlement` — tylko podpowiedź,
 * pulę roku zatwierdzają Kadry.
 */
export function statutoryEntitlement(
  form: EmploymentType | null | undefined,
  seniorityYears: number | null | undefined,
): number | null {
  if (form !== "uop" || seniorityYears == null || !Number.isFinite(seniorityYears)) return null;
  return seniorityYears >= 10 ? 26 : 20;
}

/** Czy Kadry mogą ustawić pulę płatnych dni (D6: zlecenie bez puli). */
export function poolAllowed(form: EmploymentType | null | undefined): boolean {
  return form !== "zlecenie";
}
