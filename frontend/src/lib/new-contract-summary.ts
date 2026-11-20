/**
 * „Nowy kontrakt” w wariancie B (decyzja Artura z 19.11.2026, makiety modułu
 * Kontrakty): obok formularza karta „Podsumowanie” mówi na bieżąco, co
 * powstanie — kto u kogo, od kiedy, stawki, marża na godzinę i w miesiącu,
 * status po kliknięciu. Tu są reguły tej karty, skrót zwiniętych
 * „Zaawansowanych” i podpowiedzi stawek z rekrutacji; strona je renderuje.
 *
 * Marżę liczymy tylko przy tej samej walucie obu stawek (klient w EUR,
 * konsultant w PLN = brak marży, jak `effective_rate_fields` w backendzie),
 * a miesiąc jak `Contract.monthly_rate`: stawka × godziny rozliczeniowe albo
 * ryczałt bez zmian.
 */

import type { RecruitmentRate } from "@/lib/api/recruitmentRates";
import {
  buildCandidateRateSchedule,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { compareRates, normalizeRateUnit } from "@/lib/recruitment-rate-check";
import { parseDecimalInput } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { HOURS_PER_MONTH } from "@/lib/work-time";

export type CreateStatus = "draft" | "active" | "ending" | "ended";

/** Status przy utworzeniu — te same etykiety co dawna lista „Status”. */
export const CREATE_STATUS_LABEL: Record<CreateStatus, string> = {
  draft: "Szkic",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
};

function asStatus(status: string): CreateStatus {
  return status in CREATE_STATUS_LABEL ? (status as CreateStatus) : "draft";
}

/** Tekst przycisku głównego: od razu mówi, co powstanie. */
export function createButtonLabel(status: string): string {
  const s = asStatus(status);
  return s === "draft" ? "Utwórz szkic" : `Utwórz jako ${CREATE_STATUS_LABEL[s].toLowerCase()}`;
}

/** „Po utworzeniu: szkic — aktywujesz go po podpisaniu umowy.” */
export function createOutcome(status: string): { status: string; detail: string } {
  const s = asStatus(status);
  const detail: Record<CreateStatus, string> = {
    draft: "aktywujesz go po podpisaniu umowy.",
    active: "wpis umowy już podpisanej, wymaga stawki klienta i konsultanta.",
    ending: "wpis podpisanej umowy, która się kończy; wymaga obu stawek.",
    ended: "wpis umowy, która już się skończyła.",
  };
  return { status: CREATE_STATUS_LABEL[s].toLowerCase(), detail: detail[s] };
}

/** Pola opcjonalne, które można dopisać później na stronie kontraktu. */
export function laterFields(input: { lineManager: string; workMode: string }): string[] {
  return [
    input.lineManager.trim() ? null : "line manager",
    input.workMode ? null : "tryb pracy",
  ].filter((v): v is string => v !== null);
}

/**
 * Stawka konsultanta w dniu startu — ten sam wybór co backend
 * (`Contract._resolve_scheduled_rate`): ostatni etap z „od” ≤ start, a gdy
 * wszystkie są późniejsze — najwcześniejszy; przy równej dacie wygrywa etap
 * dopisany później.
 */
export function candidateRateOnStart(
  rows: RateScheduleRow[],
  startDate: string,
): number | null {
  const steps = buildCandidateRateSchedule(rows, startDate).map((step, index) => ({
    step,
    index,
  }));
  if (steps.length === 0) return null;
  const past = steps.filter(({ step }) => step.effective_from <= startDate);
  const earliest = steps.reduce(
    (min, { step }) => (step.effective_from < min ? step.effective_from : min),
    steps[0].step.effective_from,
  );
  const pool = past.length > 0 ? past : steps.filter(({ step }) => step.effective_from === earliest);
  const chosen = pool.reduce((best, item) =>
    item.step.effective_from > best.step.effective_from ||
    (item.step.effective_from === best.step.effective_from && item.index > best.index)
      ? item
      : best,
  );
  return chosen.step.rate;
}

export interface ContractMoneyInput {
  clientRate: number | null;
  candidateRate: number | null;
  clientCurrency: string;
  candidateCurrency: string;
  /** `hourly` albo `monthly` (Kontrakty nie mają stawek w MD). */
  rateUnit: string;
  /** Pole „Godziny w miesiącu” — puste albo zero liczy się jak 168. */
  billingHours: number | null;
}

export interface ContractMoneyFacts {
  sameCurrency: boolean;
  /** Ile godzin liczy miesiąc; `null` = ryczałt miesięczny. */
  hours: number | null;
  marginPerUnit: number | null;
  marginPct: number | null;
  monthlyRevenue: number | null;
  monthlyCost: number | null;
  monthlyMargin: number | null;
}

export function contractMoney(input: ContractMoneyInput): ContractMoneyFacts {
  const monthly = input.rateUnit === "monthly";
  const hours = monthly ? null : input.billingHours && input.billingHours > 0 ? input.billingHours : HOURS_PER_MONTH;
  const factor = hours ?? 1;
  const sameCurrency =
    input.clientCurrency.trim().toUpperCase() === input.candidateCurrency.trim().toUpperCase();
  const { clientRate, candidateRate } = input;
  const marginPerUnit =
    sameCurrency && clientRate != null && candidateRate != null ? clientRate - candidateRate : null;
  return {
    sameCurrency,
    hours,
    marginPerUnit,
    marginPct:
      marginPerUnit != null && clientRate != null && clientRate !== 0
        ? (marginPerUnit / clientRate) * 100
        : null,
    monthlyRevenue: clientRate != null ? clientRate * factor : null,
    monthlyCost: candidateRate != null ? candidateRate * factor : null,
    monthlyMargin: marginPerUnit != null ? marginPerUnit * factor : null,
  };
}

/** „29,9 %” — procent z jednym miejscem po przecinku. */
export function formatPctPl(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}

/** „157,00” — wartość do pola stawki (przecinek, bez spacji tysięcy). */
export function rateToInput(value: number | string | null | undefined): string {
  if (value == null || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toFixed(2).replace(".", ",") : "";
}

export interface AdvancedSummaryInput {
  canManageFinance: boolean;
  clientCurrency: string;
  candidateCurrency: string;
  rateUnit: string;
  billingHours: string;
  frameworkRows: RateScheduleRow[];
  candidateRows: RateScheduleRow[];
  consumption: string;
  consumptionUnit: string;
  status: string;
}

function filledRows(rows: RateScheduleRow[]): number {
  return rows.filter((row) => row.rate.trim() !== "").length;
}

/** Jedna linia przy zwiniętych „Zaawansowanych”: co w nich dziś stoi. */
export function advancedSummary(input: AdvancedSummaryInput): string {
  const parts: string[] = [];
  if (input.canManageFinance) {
    parts.push(
      input.clientCurrency === input.candidateCurrency
        ? input.clientCurrency
        : `${input.clientCurrency} / ${input.candidateCurrency}`,
    );
    parts.push(
      input.rateUnit === "monthly"
        ? "ryczałt miesięczny"
        : `godzinowo, ${Number(input.billingHours) || HOURS_PER_MONTH} h/mies.`,
    );
    parts.push(filledRows(input.frameworkRows) > 0 ? "stawka ramowa" : "bez stawki ramowej");
    const changes = Math.max(0, filledRows(input.candidateRows) - 1);
    parts.push(
      changes === 0
        ? "bez zmian stawki"
        : countPl(changes, "zmiana stawki", "zmiany stawki", "zmian stawki"),
    );
  }
  parts.push(
    input.consumption.trim()
      ? `zużycie ${input.consumption} ${input.consumptionUnit === "md" ? "MD" : "RBH"}`
      : "bez zużycia zamówienia",
  );
  parts.push(`status: ${CREATE_STATUS_LABEL[asStatus(input.status)].toLowerCase()}`);
  return parts.join(" · ");
}

export interface RecruitmentRateHint {
  /** „z rekrutacji: 157,00 zł/h · Anna Nowak, 27.10.2026” */
  text: string;
  /** Pole zgadza się ze stawką z rekrutacji. */
  matches: boolean;
  /** Wartość wpisywana przez „Użyj”; `null` = bez przycisku. */
  useValue: string | null;
}

/**
 * Podpowiedź pod polem stawki (D7): stawka z rekrutacji tej pary. Nigdy nie
 * blokuje zapisu i nie wpisuje się sama. „Użyj” jest tylko przy stawce
 * konsultanta w tej samej jednostce i walucie — stawkę klienta Artur wybrał
 * jako samą informację (karta „Stawki finansowe”, 29.10.2026), bo przychód
 * w kontrakcie przed zamówieniem gasi Finansom dzwonek „bez zamówienia”.
 */
export function recruitmentRateHint(
  rate: RecruitmentRate | null | undefined,
  leg: "client" | "candidate",
  form: { value: string; unit: string; currency: string },
): RecruitmentRateHint | null {
  if (!rate) return null;
  const value = leg === "client" ? rate.client_rate_value : rate.candidate_rate_value;
  if (value == null || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  const unit = leg === "client" ? rate.client_rate_unit : rate.candidate_rate_unit;
  const currency = (leg === "client" ? rate.client_rate_currency : rate.candidate_rate_currency) || "PLN";
  const at = leg === "client" ? rate.client_rate_at : rate.candidate_rate_at;
  const who = leg === "client" ? rate.client_rate_by_name : null;
  const when = at ? formatIsoDatePl(warsawDateOf(at) ?? at) : null;
  const note = [who, when].filter(Boolean).join(", ");

  const formValue = parseDecimalInput(form.value);
  const sameKind =
    normalizeRateUnit(unit) !== null &&
    normalizeRateUnit(unit) === normalizeRateUnit(form.unit) &&
    currency.toUpperCase() === form.currency.toUpperCase();
  const matches =
    formValue != null &&
    (compareRates({ value, unit, currency }, { value: formValue, unit: form.unit, currency: form.currency }) ===
      "equal" ||
      (sameKind && Math.abs(formValue - numeric) < 0.005));
  return {
    text: `${matches ? "z rekrutacji" : "w rekrutacji"}: ${formatMoney(numeric, currency, unit)}${note ? ` · ${note}` : ""}`,
    matches,
    useValue: leg === "candidate" && sameKind && !matches ? rateToInput(numeric) : null,
  };
}
