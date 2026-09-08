/**
 * Bramka budżetowa ruchu na „Zweryfikowany" — lustro
 * `backend/app/services/rate_normalization.py` (polityka `168h-21d-v1`).
 *
 * Powód istnienia tego modułu: krok 05 („Screening", program „flow w języku
 * C2") pokazuje werdykt bramki W DOKU, ZANIM ktokolwiek kliknie — kontrakt
 * programu mówi, że akcja zablokowana ma być widoczna z powodem, a nie
 * kończyć się niespodzianką po ruchu. Skoro ten sam werdykt liczy też
 * `VerifiedRateModal` (ta sama decyzja, dwa miejsca), liczy go JEDNA funkcja.
 *
 * Uwaga na semantykę: `Job.salary_max` jest budżetem MIESIĘCZNYM w PLN, więc
 * stawkę kandydata trzeba znormalizować przed porównaniem. Modal porównywał
 * dotąd surowe liczby (`118 > 20000` → „mieści się"), więc dla stawki
 * godzinowej potrafił obiecać ruch bez akceptacji, a backend i tak stawiał
 * kartę na „Pending" (118 × 168 = 19 824 mieści się, ale 130 × 168 = 21 840
 * już nie). Zapowiedź inna niż decyzja serwera jest gorsza niż jej brak.
 *
 * Fail-closed jak backend: nieznana jednostka albo waluta ≠ PLN → nie
 * porównujemy, tylko zapowiadamy akceptację (`needs_approval`), bo dokładnie
 * to zrobi serwer.
 */

import type { RateUnit } from "@/lib/api";

/** `hourly → 21 dni × 8 h`, `daily → 21 dni` (polityka `168h-21d-v1`). */
export const MONTHLY_FACTOR: Record<RateUnit, number> = {
  hourly: 168,
  daily: 21,
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

/** Werdykt bramki — dokładnie trzy rozłączne odpowiedzi. */
export type RateGateVerdict =
  /** Brak `salary_max` na ofercie → nie ma z czym porównywać, ruch przechodzi. */
  | "no_budget"
  /** Mieści się w budżecie — ruch bez akceptacji. */
  | "within_budget"
  /** Ponad budżet albo nieporównywalne → karta „Pending" + powiadomienie. */
  | "needs_approval";

export interface RateGateResult {
  /** Liczba wyparsowana z pola (przecinek dziesiętny dozwolony). */
  numericRate: number;
  /** Czy w ogóle wolno wysłać ruch (backend wymaga wartości i jednostki). */
  isValid: boolean;
  /** `null`, gdy nie da się porównać (waluta ≠ PLN / nieznana jednostka). */
  normalizedMonthly: number | null;
  verdict: RateGateVerdict;
  /** Zdanie po polsku pod pole — to samo w modalu i w doku kroku 05. */
  message: string | null;
}

export interface RateGateInput {
  /** Surowa treść pola (dopuszczamy „118,50"). */
  rawRate: string;
  unit: RateUnit;
  currency?: string;
  /** `Job.salary_max` — budżet miesięczny w PLN. `null` = brak budżetu. */
  jobBudgetMax: number | null;
}

const formatPln = (n: number) => n.toLocaleString("pl-PL");

export function evaluateRateGate({
  rawRate,
  unit,
  currency = "PLN",
  jobBudgetMax,
}: RateGateInput): RateGateResult {
  const numericRate = Number.parseFloat(rawRate.replace(",", "."));
  const isValid = Number.isFinite(numericRate) && numericRate > 0;
  const normalizedMonthly = isValid
    ? normalizeRateToMonthly(numericRate, unit, currency)
    : null;

  if (!isValid) {
    return {
      numericRate,
      isValid,
      normalizedMonthly: null,
      verdict: jobBudgetMax === null ? "no_budget" : "needs_approval",
      message: null,
    };
  }

  if (jobBudgetMax === null) {
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict: "no_budget",
      message:
        "Ta rekrutacja nie ma wpisanego budżetu, więc nie ma z czym porównać stawki — ruch przechodzi bez akceptacji.",
    };
  }

  if (normalizedMonthly === null) {
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict: "needs_approval",
      message:
        "Nie da się porównać tej stawki z budżetem (waluta inna niż PLN albo nieznana jednostka) — karta trafi na „Pending” do akceptacji.",
    };
  }

  if (normalizedMonthly > jobBudgetMax) {
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict: "needs_approval",
      message:
        `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedMonthly)} PLN/mc — ` +
        `powyżej budżetu ${formatPln(jobBudgetMax)} PLN/mc. Karta trafi na „Pending”, ` +
        "a approverzy (admin / Delivery Lead / HoR) dostaną powiadomienie.",
    };
  }

  return {
    numericRate,
    isValid,
    normalizedMonthly,
    verdict: "within_budget",
    message:
      `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedMonthly)} PLN/mc — ` +
      `mieści się w budżecie ${formatPln(jobBudgetMax)} PLN/mc. Ruch bez akceptacji.`,
  };
}
