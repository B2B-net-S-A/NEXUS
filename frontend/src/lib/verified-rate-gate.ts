/**
 * Porównanie stawki z budżetem przy ruchu na „Zweryfikowany" — WYŁĄCZNIE
 * informacyjne od 17.09.2026.
 *
 * Do tego dnia werdykt zapowiadał bramkę serwera: stawka ponad `salary_max`
 * (budżet MIESIĘCZNY) stawiała kartę na „Pending" do akceptacji admina.
 * Decyzja właściciela: żadna bramka nie zatrzymuje przepływu. Zostaje sygnał
 * „ponad budżet" — w oknie i jako odznaka na karcie — liczony względem budżetu
 * GODZINOWEGO rekrutacji (`effective_budget_hourly`, ta sama liczba co
 * nagłówek i wyszukiwanie). Przeliczenie stawki: `lib/rate-to-hourly.ts`.
 *
 * `MONTHLY_FACTOR` i `normalizeRateToMonthly` zostają dla ekranów, które
 * pokazują przelicznik miesięczny obok `budget_max_at_move` (dok karty).
 */

import type { RateUnit } from "@/lib/api";
import { rateToHourly } from "@/lib/rate-to-hourly";
import { HOURS_PER_MONTH, MD_PER_MONTH } from "@/lib/work-time";

/** `hourly → 21 dni × 8 h`, `daily → 21 dni` (polityka `168h-21d-v1`). */
export const MONTHLY_FACTOR: Record<RateUnit, number> = {
  hourly: HOURS_PER_MONTH,
  daily: MD_PER_MONTH,
  monthly: 1,
};

export const RATE_UNIT_LABELS: Record<RateUnit, string> = {
  hourly: "PLN / godzinę",
  daily: "PLN / dzień",
  monthly: "PLN / miesiąc",
};

/** Krótka jednostka do zdań i pigułek („118 PLN/h"). */
export const RATE_UNIT_SHORT: Record<RateUnit, string> = {
  hourly: "PLN/h",
  daily: "PLN/dzień",
  monthly: "PLN/mc",
};

/**
 * `null` = „nie da się bezpiecznie porównać" — caller MUSI potraktować to jak
 * manual review, nigdy jak auto-approve (ta sama umowa co w backendzie).
 */
export function normalizeRateToMonthly(
  value: number,
  unit: RateUnit | null | undefined,
  currency: string | null | undefined,
): number | null {
  const cur = (currency ?? "PLN").trim().toUpperCase();
  if (cur !== "PLN") return null;
  const factor = unit ? MONTHLY_FACTOR[unit] : undefined;
  if (factor === undefined) return null;
  if (!Number.isFinite(value)) return null;
  return Math.round(value * factor * 100) / 100;
}

/** Werdykt porównania — dokładnie trzy rozłączne odpowiedzi, żadna nie blokuje. */
export type RateGateVerdict =
  /** Brak budżetu godzinowego albo stawka nie do porównania (waluta ≠ PLN). */
  | "no_budget"
  /** Mieści się w budżecie. */
  | "within_budget"
  /** Ponad budżet — ostrzeżenie w oknie i odznaka „ponad budżet" na karcie. */
  | "over_budget";

export interface RateGateResult {
  /** Liczba wyparsowana z pola (przecinek dziesiętny dozwolony). */
  numericRate: number;
  /** Czy pole zawiera stawkę do zapisania (stawka jest opcjonalna). */
  isValid: boolean;
  /** Stawka w PLN/h; `null`, gdy nie da się porównać. */
  normalizedHourly: number | null;
  verdict: RateGateVerdict;
  /** Zdanie po polsku pod pole — to samo w oknie i w doku kroku 05. */
  message: string | null;
}

export interface RateGateInput {
  /** Surowa treść pola (dopuszczamy „118,50"). */
  rawRate: string;
  unit: RateUnit;
  currency?: string;
  /** Budżet PLN/h rekrutacji (`effective_budget_hourly`). `null` = brak. */
  jobBudgetHourly: number | null;
}

const formatPln = (n: number) => n.toLocaleString("pl-PL");

export function evaluateRateGate({
  rawRate,
  unit,
  currency = "PLN",
  jobBudgetHourly,
}: RateGateInput): RateGateResult {
  const numericRate = Number.parseFloat(rawRate.replace(",", "."));
  const isValid = Number.isFinite(numericRate) && numericRate > 0;
  const normalizedHourly = isValid
    ? rateToHourly(numericRate, unit, currency)
    : null;

  if (!isValid) {
    return {
      numericRate,
      isValid,
      normalizedHourly: null,
      verdict: "no_budget",
      message: null,
    };
  }

  if (jobBudgetHourly === null) {
    return {
      numericRate,
      isValid,
      normalizedHourly,
      verdict: "no_budget",
      message:
        "Ta rekrutacja nie ma wpisanego budżetu godzinowego — stawka zostanie zapisana bez porównania.",
    };
  }

  if (normalizedHourly === null) {
    return {
      numericRate,
      isValid,
      normalizedHourly,
      verdict: "no_budget",
      message:
        "Waluta inna niż PLN albo nieznana jednostka — nie porównujemy z budżetem; stawka zostanie zapisana.",
    };
  }

  if (normalizedHourly > jobBudgetHourly) {
    return {
      numericRate,
      isValid,
      normalizedHourly,
      verdict: "over_budget",
      message:
        `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedHourly)} PLN/h — ` +
        `powyżej budżetu ${formatPln(jobBudgetHourly)} PLN/h. Ruch przejdzie, a karta dostanie odznakę „ponad budżet”.`,
    };
  }

  return {
    numericRate,
    isValid,
    normalizedHourly,
    verdict: "within_budget",
    message:
      `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedHourly)} PLN/h — ` +
      `mieści się w budżecie ${formatPln(jobBudgetHourly)} PLN/h.`,
  };
}
