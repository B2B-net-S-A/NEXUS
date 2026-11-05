// Premia 200% — czyste funkcje opisu warunków (karta Płac i „Moja współpraca”).

import type { DoubleBonusDl, DoubleBonusRecruiter } from "@/lib/api/hr-payroll";

const decimal = (value: string | null | undefined, digits = 1): string =>
  value == null ? "—" : Number(value).toLocaleString("pl-PL", { maximumFractionDigits: digits });

/** „placementy 1/2 · weryfikacje 3,2/dzień · precision 87%” albo średnia marża DL. */
export function doubleBonusConditions(row: DoubleBonusRecruiter | DoubleBonusDl): string {
  if (row.kind === "dl") {
    const missing = row.missing_margins ? ` · bez stawki: ${row.missing_margins}` : "";
    return `placementy ${row.placements} · średnia marża ${decimal(row.average_margin, 2)} zł/h${missing}`;
  }
  const target = row.target ?? "—";
  const precision = row.precision_pct == null ? "—" : `${decimal(row.precision_pct, 0)}%`;
  return `placementy ${row.placements}/${target} · weryfikacje ${decimal(row.verifications_per_day)}/dzień · precision ${precision}`;
}

export interface DoubleBonusState {
  label: string;
  tone: "success" | "neutral";
}

/**
 * Stan osoby: w trakcie miesiąca — czy na dziś spełnia warunki; po końcu —
 * zapisana decyzja, a przed zapisem wynik na dziś. Różnica (np. stawka dopisana
 * po decyzji) daje dopisek, że trzeba przeliczyć wynik.
 */
export function doubleBonusState(
  row: DoubleBonusRecruiter | DoubleBonusDl,
  final: boolean,
): DoubleBonusState {
  if (!final) {
    return row.qualified
      ? { label: "na dziś spełnia", tone: "success" }
      : { label: "jeszcze nie", tone: "neutral" };
  }
  const decided = row.decided ?? row.qualified;
  const stale = row.decided !== undefined && row.decided !== row.qualified;
  const suffix = stale ? " · do przeliczenia" : "";
  return decided
    ? { label: `200%${suffix}`, tone: "success" }
    : { label: `zwykła premia${suffix}`, tone: "neutral" };
}

/** Kwoty progów z serwera („4.0”) jako liczby na pasek postępu. */
export function progressShare(value: string | number | null | undefined, goal: string | number): number {
  const current = Number(value ?? 0);
  const target = Number(goal);
  if (!Number.isFinite(current) || !Number.isFinite(target) || target <= 0) return current > 0 ? 100 : 0;
  return Math.max(0, Math.min(100, Math.round((current / target) * 100)));
}
