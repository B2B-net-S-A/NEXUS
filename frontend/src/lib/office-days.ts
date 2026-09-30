/**
 * Dni w biurze rekrutacji: „w tygodniu” albo „w miesiącu” (0406, 30.09.2026).
 *
 * Lustro `backend/app/services/office_days.py` — wspólne przypadki
 * w `__fixtures__/office-days-cases.json`. Człowiek podaje jedno z dwóch;
 * przy wpisie miesięcznym liczbę tygodniową (czytaną przez bramki dopasowań)
 * wylicza serwer i nigdy nie jest ona zerem.
 */

export type OfficeDaysPeriod = "week" | "month";

export const WEEKLY_MAX = 7;
export const MONTHLY_MAX = 22;
const WEEKS_PER_MONTH = 52 / 12;

export function weeklyFromMonthly(perMonth: number): number {
  return Math.max(1, Math.min(WEEKLY_MAX, Math.floor(perMonth / WEEKS_PER_MONTH + 0.5)));
}

function days(n: number): string {
  return n === 1 ? "1 dzień" : `${n} dni`;
}

/** „2 dni w miesiącu” / „3 dni w tygodniu”; `null`, gdy nic nie podano. */
export function officeDaysLabel(
  perWeek: number | null | undefined,
  perMonth: number | null | undefined,
): string | null {
  if (perMonth != null) return `${days(perMonth)} w miesiącu`;
  if (perWeek != null) return `${days(perWeek)} w tygodniu`;
  return null;
}

/** Krótko, do podsumowań: „2 dni/mies.”, „3 dni/tydz.”. */
export function officeDaysShort(
  perWeek: number | null | undefined,
  perMonth: number | null | undefined,
): string | null {
  if (perMonth != null) return `${days(perMonth)}/mies.`;
  if (perWeek != null) return `${days(perWeek)}/tydz.`;
  return null;
}

/** Liczba z pola formularza w zakresie okresu; `null` = puste albo błędne. */
export function parseOfficeDaysInput(
  value: string,
  period: OfficeDaysPeriod,
): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  if (!Number.isInteger(n)) return null;
  return period === "month"
    ? n >= 1 && n <= MONTHLY_MAX
      ? n
      : null
    : n >= 0 && n <= WEEKLY_MAX
      ? n
      : null;
}

/**
 * Para pól zapisu. Miesięcznie tylko przy pracy hybrydowej — przy innym
 * trybie wpis miesięczny jest niepoprawny (`null` w obu polach = brak).
 */
export function officeDaysFields(
  value: string,
  period: OfficeDaysPeriod,
  remotePolicy: string | null | undefined,
): { onsite_days_per_week: number | null; onsite_days_per_month: number | null } {
  const n = parseOfficeDaysInput(value, period);
  if (period === "month") {
    if (n == null || remotePolicy !== "hybrid") {
      return { onsite_days_per_week: null, onsite_days_per_month: null };
    }
    return { onsite_days_per_week: weeklyFromMonthly(n), onsite_days_per_month: n };
  }
  return { onsite_days_per_week: n, onsite_days_per_month: null };
}

/** Stan formularza z zapisanej pary pól. */
export function officeDaysFormValue(
  perWeek: number | null | undefined,
  perMonth: number | null | undefined,
): { value: string; period: OfficeDaysPeriod } {
  if (perMonth != null) return { value: String(perMonth), period: "month" };
  return { value: perWeek != null ? String(perWeek) : "", period: "week" };
}
