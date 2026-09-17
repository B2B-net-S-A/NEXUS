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
 * Od 17.09.2026 bramka „Pending" jest WYŁĄCZONA (decyzja Artura,
 * `PENDING_VERIFICATION_ENABLED=false`): ruch zawsze przechodzi, a werdykt
 * jest wyłącznie informacją. Stawka ponad budżet (`over_budget`) zostaje
 * zapisana, a karta dostaje odznakę „ponad budżet". Nieznana jednostka albo
 * waluta ≠ PLN → `not_comparable` (nie zgadujemy przekroczenia).
 */

import type { RateUnit } from "@/lib/api";
import { hasRole } from "@/store/auth";

type RoleBearingUser = Parameters<typeof hasRole>[0];

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

/** Werdykt bramki — informacja, nigdy blokada (bramka „Pending" wyłączona). */
export type RateGateVerdict =
  /** Brak `salary_max` na rekrutacji → nie ma z czym porównywać. */
  | "no_budget"
  /**
   * Budżet istnieje, ale jest ukryty dla roli (Delivery Lead / TCM dostają
   * `salary_max = null`). Bez tego wariantu ekran twierdziłby „brak budżetu",
   * czyli coś, co nie jest prawdą.
   */
  | "budget_hidden"
  /** Mieści się w budżecie. */
  | "within_budget"
  /** Ponad budżet — ruch przechodzi, karta dostaje odznakę „ponad budżet". */
  | "over_budget"
  /** Waluta ≠ PLN albo nieznana jednostka — nie da się porównać. */
  | "not_comparable";

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
  /** `Job.salary_max` — budżet miesięczny w PLN. `null` = brak albo ukryty. */
  jobBudgetMax: number | null;
  /**
   * `true`, gdy `jobBudgetMax === null` wynika z redakcji dla roli, a nie
   * z braku budżetu — patrz {@link isJobBudgetHiddenFor}.
   */
  budgetHidden?: boolean;
}

/**
 * Lustro `_redact_delivery_lead_job_finance` (backend/app/api/jobs.py):
 * Delivery Lead i TCM bez roli admina dostają `salary_min/max = null`.
 */
export function isJobBudgetHiddenFor(
  user: RoleBearingUser | null | undefined,
): boolean {
  return (
    hasRole(user, "delivery_lead", "talent_community_manager") &&
    !hasRole(user, "admin")
  );
}

const formatPln = (n: number) => n.toLocaleString("pl-PL");

export function evaluateRateGate({
  rawRate,
  unit,
  currency = "PLN",
  jobBudgetMax,
  budgetHidden = false,
}: RateGateInput): RateGateResult {
  const numericRate = Number.parseFloat(rawRate.replace(",", "."));
  const isValid = Number.isFinite(numericRate) && numericRate > 0;
  const normalizedMonthly = isValid
    ? normalizeRateToMonthly(numericRate, unit, currency)
    : null;

  if (jobBudgetMax === null) {
    const verdict: RateGateVerdict = budgetHidden ? "budget_hidden" : "no_budget";
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict,
      message: !isValid
        ? null
        : budgetHidden
          ? "Budżet ukryty dla Twojej roli — stawka zostanie zapisana, a ewentualne przekroczenie pokaże karta."
          : "Ta rekrutacja nie ma wpisanego budżetu, więc nie ma z czym porównać stawki.",
    };
  }

  if (!isValid) {
    return {
      numericRate,
      isValid,
      normalizedMonthly: null,
      verdict: "within_budget",
      message: null,
    };
  }

  if (normalizedMonthly === null) {
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict: "not_comparable",
      message:
        "Nie da się porównać tej stawki z budżetem (waluta inna niż PLN albo nieznana jednostka) — stawka zostanie zapisana bez porównania.",
    };
  }

  if (normalizedMonthly > jobBudgetMax) {
    return {
      numericRate,
      isValid,
      normalizedMonthly,
      verdict: "over_budget",
      message:
        `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedMonthly)} PLN/mc — ` +
        `powyżej budżetu ${formatPln(jobBudgetMax)} PLN/mc. Ruch przechodzi, ` +
        "a karta dostanie odznakę „ponad budżet” (informacja, bez akceptacji).",
    };
  }

  return {
    numericRate,
    isValid,
    normalizedMonthly,
    verdict: "within_budget",
    message:
      `${formatPln(numericRate)} ${RATE_UNIT_SHORT[unit]} to ${formatPln(normalizedMonthly)} PLN/mc — ` +
      `mieści się w budżecie ${formatPln(jobBudgetMax)} PLN/mc.`,
  };
}
