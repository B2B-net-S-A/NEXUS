/**
 * Teksty faktów o osobie w panelu osoby i w przeglądzie Delivery Leada
 * (jeden panel osoby, 04.10.2026). Do tej pory dok i przegląd liczyły
 * dostępność i stawkę każdy po swojemu: dok pokazywał „140 PLN/hourly”
 * i gubił status dostępności, przegląd — „140 zł/h” ze statusem.
 */

import type { RateUnit } from "@/lib/api";
import { normalizeRateToMonthly } from "@/lib/verified-rate-gate";
import { formatDate } from "@/lib/utils";

export type ClientRateUnit = "hourly" | "daily" | "monthly";

export const RATE_UNIT_LABEL: Record<ClientRateUnit, string> = {
  hourly: "zł/h",
  daily: "zł/MD",
  monthly: "zł/mies.",
};

function formatAmount(value: number): string {
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
}

/** „140 zł/h”, „900 zł/MD”, „40 EUR/h”; nieczytelna kwota = `null`. */
export function rateText(
  value: number | string | null | undefined,
  unit: string | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "number" ? value : Number.parseFloat(String(value).replace(",", "."));
  if (!Number.isFinite(numeric)) return null;
  const cur = (currency ?? "PLN").toUpperCase();
  const unitLabel = unit && unit in RATE_UNIT_LABEL ? RATE_UNIT_LABEL[unit as ClientRateUnit] : null;
  if (cur === "PLN") return `${formatAmount(numeric)} ${unitLabel ?? "zł"}`;
  const suffix = unitLabel ? unitLabel.replace("zł", cur) : cur;
  return `${formatAmount(numeric)} ${suffix}`;
}

const AVAILABILITY_STATUS: Record<string, string> = {
  actively_looking: "Szuka aktywnie",
  open_to_offers: "Otwarty na oferty",
  not_looking: "Nie szuka",
  available: "Dostępny",
};

const NOTICE_UNIT: Record<string, string> = { days: "dni", weeks: "tyg.", months: "mies." };

export interface AvailabilityInput {
  /** Data dostępności z profilu (`availability_date` / `available_from`). */
  date?: string | null;
  status?: string | null;
  noticePeriod?: number | null;
  noticeUnit?: string | null;
}

/** „od 01.11.2026”, „Otwarty na oferty · wypowiedzenie 1 mies.”; brak = `null`. */
export function availabilityText(a: AvailabilityInput | null | undefined): string | null {
  if (!a) return null;
  if (a.date) return `od ${formatDate(a.date)}`;
  const status = a.status ? (AVAILABILITY_STATUS[a.status] ?? null) : null;
  if (a.noticePeriod != null && a.noticeUnit && a.noticeUnit in NOTICE_UNIT) {
    const notice = `wypowiedzenie ${a.noticePeriod} ${NOTICE_UNIT[a.noticeUnit]}`;
    return status ? `${status} · ${notice}` : notice;
  }
  return status;
}

/** 0 dni w biurze = wyłącznie zdalnie (kolumna `max_onsite_days_per_week`). */
export function onsiteText(days: number | null | undefined): string | null {
  if (days == null) return null;
  return days === 0 ? "Zdalnie" : `Do ${days} dni w biurze`;
}

export type BudgetVerdict = "none" | "incomparable" | "over" | "within";

/**
 * Stawka kandydata wobec MIESIĘCZNEGO budżetu zapisanego przy ruchu na
 * „Zweryfikowany” (`budget_max_at_move`). Porównanie po przeliczeniu na
 * miesiąc (168 h = 21 dni × 8 h); nieznana jednostka albo waluta ≠ PLN to
 * „nie do porównania”, nigdy „w budżecie”. Tylko informacja — nic nie blokuje.
 */
export function budgetCheck(
  value: number | string | null | undefined,
  unit: RateUnit | null | undefined,
  currency: string | null | undefined,
  budgetMonthly: number | null | undefined,
): { verdict: BudgetVerdict; monthly: number | null } {
  if (value == null || value === "" || budgetMonthly == null) {
    return { verdict: "none", monthly: null };
  }
  const numeric = Number.parseFloat(String(value).replace(",", "."));
  const monthly = Number.isFinite(numeric) ? normalizeRateToMonthly(numeric, unit, currency) : null;
  if (monthly == null) return { verdict: "incomparable", monthly: null };
  return { verdict: monthly > budgetMonthly ? "over" : "within", monthly };
}
