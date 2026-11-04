/**
 * „Kandydaci do zamknięcia” — kafelek pulpitu (prośba Olafa, decyzje Artura 20.10.2026).
 *
 * Osoby w kolumnie Tablicy „Akceptacja i umowa” (zaakceptowany, umowa
 * wysłana, podpisana) z `GET /api/board-tasks/closing`. Serwer zwraca stawki
 * pary; stawkę do klienta ukrywa rolom bez prawa do niej
 * (`show_client_rate: false`) — wtedy kafelek nie pokazuje przychodu ani
 * marży. Marża = stawka do klienta − stawka kandydata, w PLN/h, tą samą
 * regułą co przegląd Delivery Leada (`computeMargin`).
 */

import type { RateUnit } from "@/lib/api";
import { generatorPrefillHref } from "@/lib/b2b-generator-register";
import { computeMargin, type MarginResult } from "@/lib/dl-review-margin";
import { rateToHourly } from "@/lib/rate-to-hourly";

export type ClosingStep = "accepted" | "sent" | "signed";

export interface ClosingCandidateRow {
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string | null;
  job_working_title: string | null;
  client_name: string | null;
  step: ClosingStep;
  since: string;
  delivery_lead_name: string | null;
  recruiter_name: string | null;
  candidate_rate_value: number | string | null;
  candidate_rate_unit: RateUnit | null;
  candidate_rate_currency: string | null;
  client_rate_value: number | string | null;
  client_rate_unit: RateUnit | null;
  client_rate_currency: string | null;
}

export interface ClosingCandidatesResponse {
  rows: ClosingCandidateRow[];
  total: number;
  /** Ile osób na każdym kroku — ze wszystkich, także spoza `rows`. */
  step_counts: Record<ClosingStep, number>;
  show_client_rate: boolean;
}

export const CLOSING_CANDIDATES_QUERY_KEY = ["dashboard", "closing-candidates"] as const;

/** Lustro kroków w nagłówku kolumny (`ContractStepChips`). */
export const CLOSING_STEP_LABEL: Record<ClosingStep, string> = {
  accepted: "Zaakceptowany",
  sent: "Umowa wysłana",
  signed: "Podpisana",
};

const UNIT_SHORT: Record<RateUnit, string> = { hourly: "h", daily: "dzień", monthly: "mc" };

/** Stawka jako tekst: PLN/h, gdy da się sprowadzić; inaczej kwota z jednostką. */
export function rateText(
  value: number | string | null,
  unit: RateUnit | null,
  currency: string | null,
): string | null {
  if (value == null || value === "") return null;
  const hourly = rateToHourly(value, unit, currency);
  const amount = typeof value === "number" ? value : Number.parseFloat(String(value));
  if (!Number.isFinite(amount)) return null;
  const shown = hourly ?? amount;
  const digits = Number.isInteger(shown) ? 0 : 2;
  const number = shown.toLocaleString("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (hourly != null) return `${number} zł/h`;
  const cur = (currency || "PLN").toUpperCase() === "PLN" ? "zł" : (currency ?? "").toUpperCase();
  return unit ? `${number} ${cur}/${UNIT_SHORT[unit]}` : `${number} ${cur}`;
}

export function closingMargin(row: ClosingCandidateRow): MarginResult {
  // Kwota bez jednostki to nie godzina — bez zgadywania.
  if (!row.client_rate_unit) return { kind: "empty" };
  return computeMargin({
    clientAmount: row.client_rate_value,
    clientUnit: row.client_rate_unit,
    clientCurrency: row.client_rate_currency ?? "PLN",
    candidateAmount: row.candidate_rate_value,
    candidateUnit: row.candidate_rate_unit,
    candidateCurrency: row.candidate_rate_currency,
  });
}

export const CLOSING_STEPS: readonly ClosingStep[] = ["accepted", "sent", "signed"];

export type ClosingFilter = ClosingStep | "all";

/** Etykiety filtra kroków — liczba mnoga, bo to grupy osób. */
export const CLOSING_FILTER_LABEL: Record<ClosingFilter, string> = {
  all: "Wszyscy",
  accepted: "Zaakceptowani",
  sent: "Umowa wysłana",
  signed: "Podpisana",
};

export interface ClosingMarginSum {
  /** Suma marży miesięcznej (zł/mc) osób z porównywalnymi stawkami; strata odejmuje. */
  monthly: number;
  /** Ile osób weszło do sumy. */
  counted: number;
}

export function closingMarginSum(rows: readonly ClosingCandidateRow[]): ClosingMarginSum {
  let monthly = 0;
  let counted = 0;
  for (const row of rows) {
    const margin = closingMargin(row);
    if (margin.kind !== "ok") continue;
    monthly += margin.monthly;
    counted += 1;
  }
  return { monthly, counted };
}

export interface ClosingNextStep {
  label: string;
  href: string;
}

/**
 * Przycisk „Następny krok” prowadzi do ISTNIEJĄCEGO ekranu, nie robi ruchu
 * sam: podpis i „Zatrudniony” mają w panelu osoby własne warunki (uprawnienie
 * „Podpis B2B”, debrief, „Jak podpisano umowę?”), których kafelek nie dubluje.
 */
export function closingNextStep(row: ClosingCandidateRow): ClosingNextStep {
  const panel = `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
  if (row.step === "accepted") {
    return { label: "Generuj umowę", href: generatorPrefillHref(row.candidate_id, row.job_id) };
  }
  if (row.step === "sent") return { label: "Sprawdź podpis", href: panel };
  return { label: "Przesuń na „Zatrudniony”", href: panel };
}
