/**
 * Stawka kandydata → PLN/h. Jedno miejsce dla odznaki „ponad budżet" na karcie
 * kanbanu, okna „Zweryfikowany" i doku screeningu.
 *
 * Budżet rekrutacji jest GODZINOWY (`JobResponse.effective_budget_hourly` —
 * ta sama liczba, którą pokazuje nagłówek rekrutacji i której używa
 * wyszukiwanie, `lib/job-budget.ts`), więc do godziny sprowadzamy STAWKĘ, nie
 * budżet do miesiąca. Ta sama polityka co `rate_normalization.py` (168 h /
 * 21 dni): dzień = 8 h, miesiąc = 168 h.
 *
 * Od 17.09.2026 porównanie jest wyłącznie informacyjne — nic nie trafia na
 * „Oczekuje". Waluta inna niż PLN = „nie do porównania" → brak odznaki,
 * nigdy fałszywe „w budżecie".
 */

import type { RateUnit } from "@/lib/api";

export const HOURS_PER_DAY = 8;
export const HOURS_PER_MONTH = 168;

const HOURLY_DIVISOR: Record<RateUnit, number> = {
  hourly: 1,
  daily: HOURS_PER_DAY,
  monthly: HOURS_PER_MONTH,
};

/** `null` = nie da się porównać (waluta ≠ PLN, nieznana jednostka, brak liczby). */
export function rateToHourly(
  value: number | string | null | undefined,
  unit: RateUnit | null | undefined,
  currency: string | null | undefined,
): number | null {
  if (value == null || value === "") return null;
  const numeric =
    typeof value === "number"
      ? value
      : Number.parseFloat(String(value).replace(",", "."));
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  if ((currency ?? "PLN").trim().toUpperCase() !== "PLN") return null;
  const divisor = unit ? HOURLY_DIVISOR[unit] : undefined;
  if (divisor === undefined) return null;
  return Math.round((numeric / divisor) * 100) / 100;
}

export interface RateBearingItem {
  expected_rate_value?: string | number | null;
  expected_rate_unit?: RateUnit | null;
  expected_rate_currency?: string | null;
}

/** Odznaka „ponad budżet": tylko gdy OBIE strony są porównywalne. */
export function isOverHourlyBudget(
  item: RateBearingItem,
  budgetHourly: number | null | undefined,
): boolean {
  if (budgetHourly == null || !(budgetHourly > 0)) return false;
  const hourly = rateToHourly(
    item.expected_rate_value,
    item.expected_rate_unit,
    item.expected_rate_currency,
  );
  return hourly != null && hourly > budgetHourly;
}
