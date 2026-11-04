/**
 * Zdania podpowiedzi „Z rekrutacji…” w oknach zamówienia i umowy (D7).
 *
 * Czyste funkcje — komponent `RecruitmentRateHint` tylko je renderuje, a testy
 * sprawdzają treść bez montowania okien. Różnica stawek to notka „sprawdź”,
 * nigdy blokada zapisu (decyzja Artura 07.10.2026).
 */

import type { RecruitmentRate } from "@/lib/api/recruitmentRates";
import {
  compareRates,
  formatRecruitmentRate,
  hourlyPln,
  normalizeRateUnit,
} from "@/lib/recruitment-rate-check";
import { formatDate } from "@/lib/utils";
import { HOURS_PER_MD } from "@/lib/work-time";

export interface FormRate {
  value: number | string | null | undefined;
  /** `hourly | daily | monthly` (formularze) albo `hour | day | month` (plan PDF). */
  unit: string | null | undefined;
  currency?: string | null;
}

function hasValue(value: unknown): boolean {
  return value != null && value !== "";
}

/** „Z rekrutacji „Java Developer” (Anna Nowak, 03.10.2026): 165 zł/h · kandydat 140 zł/h”. */
export function recruitmentRateLine(rate: RecruitmentRate | null | undefined): string | null {
  if (!rate) return null;
  const parts: string[] = [];
  if (hasValue(rate.client_rate_value)) {
    parts.push(formatRecruitmentRate(rate.client_rate_value, rate.client_rate_unit));
  }
  if (hasValue(rate.candidate_rate_value)) {
    parts.push(
      `kandydat ${formatRecruitmentRate(rate.candidate_rate_value, rate.candidate_rate_unit)}`,
    );
  }
  if (parts.length === 0) return null;
  const who = [rate.client_rate_by_name, rate.client_rate_at ? formatDate(rate.client_rate_at) : null]
    .filter((item): item is string => Boolean(item))
    .join(", ");
  const title = rate.job_title ? ` „${rate.job_title}”` : "";
  return `Z rekrutacji${title}${who ? ` (${who})` : ""}: ${parts.join(" · ")}`;
}

/** Notki przy różnicy — puste, gdy stawki się zgadzają albo nie da się ich porównać. */
export function recruitmentRateNotes(
  rate: RecruitmentRate | null | undefined,
  form: { revenue?: FormRate | null; cost?: FormRate | null },
): string[] {
  if (!rate) return [];
  const notes: string[] = [];
  if (
    form.revenue &&
    hasValue(rate.client_rate_value) &&
    compareRates(
      {
        value: rate.client_rate_value,
        unit: rate.client_rate_unit,
        currency: rate.client_rate_currency,
      },
      form.revenue,
    ) === "differs"
  ) {
    notes.push(
      `Stawka przychodowa różni się od stawki do klienta z rekrutacji (${formatRecruitmentRate(
        rate.client_rate_value,
        rate.client_rate_unit,
      )}) — sprawdź. Jeśli klient przyjął inną stawkę, popraw stawkę do klienta w rekrutacji.`,
    );
  }
  if (
    form.cost &&
    hasValue(rate.candidate_rate_value) &&
    compareRates(
      {
        value: rate.candidate_rate_value,
        unit: rate.candidate_rate_unit,
        currency: rate.candidate_rate_currency,
      },
      form.cost,
    ) === "differs"
  ) {
    notes.push(
      `Stawka kosztowa różni się od stawki kandydata z rekrutacji (${formatRecruitmentRate(
        rate.candidate_rate_value,
        rate.candidate_rate_unit,
      )}) — sprawdź.`,
    );
  }
  return notes;
}

/**
 * Notka pod „Stawka godz. (netto)” w Generatorze umów B2B: pierwszy etap
 * stawki umowy kontra stawka kandydata z rekrutacji. Nie walidacja i nie
 * toast — umowę da się wygenerować z każdą stawką.
 */
export function contractRateNote(
  recruitment:
    | {
        value: number | string | null;
        unit: string | null;
        currency: string | null;
        job_title?: string | null;
      }
    | null
    | undefined,
  firstStageRate: string | number | null | undefined,
  currency: string | null | undefined,
): string | null {
  if (!recruitment || !hasValue(recruitment.value) || !hasValue(firstStageRate)) {
    return null;
  }
  const verdict = compareRates(
    { value: recruitment.value, unit: recruitment.unit, currency: recruitment.currency },
    { value: firstStageRate, unit: "hourly", currency },
  );
  if (verdict !== "differs") return null;
  const title = recruitment.job_title ? ` „${recruitment.job_title}”` : "";
  return `Stawka kandydata z rekrutacji${title}: ${formatRecruitmentRate(
    recruitment.value,
    recruitment.unit,
  )} — wpisana stawka się różni, sprawdź przed wysłaniem umowy.`;
}

/**
 * Ostrzeżenie na karcie konsultanta zamówienia MD/kosztowego: stawka
 * przychodowa linii kontra stawka do klienta z rekrutacji (× 8 przy MD).
 * `null` = zgodne, nieporównywalne albo brak stawki w rekrutacji.
 */
export function lineRevenueWarning(
  rate: RecruitmentRate | null | undefined,
  revenue: FormRate,
): string | null {
  if (!rate || !hasValue(rate.client_rate_value)) return null;
  const reference = {
    value: rate.client_rate_value,
    unit: rate.client_rate_unit,
    currency: rate.client_rate_currency,
  };
  if (compareRates(reference, revenue) !== "differs") return null;
  const hourly = hourlyPln(reference.value, reference.unit, reference.currency);
  const lineIsMd = normalizeRateUnit(revenue.unit) === "day";
  const referenceText =
    lineIsMd && hourly != null && normalizeRateUnit(reference.unit) === "hour"
      ? `${formatRecruitmentRate(reference.value, reference.unit)} × 8 = ${formatRecruitmentRate(
          hourly * HOURS_PER_MD,
          "md",
        )}`
      : formatRecruitmentRate(reference.value, reference.unit);
  const title = rate.job_title ? ` „${rate.job_title}”` : "";
  return `Stawka przychodowa różni się od stawki do klienta z rekrutacji${title} (${referenceText}) — sprawdź. Zapis nie jest blokowany.`;
}
