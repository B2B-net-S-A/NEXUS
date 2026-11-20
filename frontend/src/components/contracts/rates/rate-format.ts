// Liczby karty „Stawki finansowe” (zakładka „Pieniądze”, wariant A z 19.11.2026).
// Kwota stawki ma format `formatMoney` z `lib/money` (2 miejsca, 3 gdy stawka
// ma ich więcej, np. 34,625 po przeliczeniu MD ÷ 8), tylko bez waluty — waluta
// i jednostka stoją obok liczby albo raz w nagłówku kolumny.
import { formatIsoDatePl } from "@/lib/date-pl";
import { currencySymbol, rateUnitSuffix } from "@/lib/money";

const RATE_2 = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const RATE_3 = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const PERCENT = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const NBP_RATE = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

/** „163,00”, „34,625”; brak albo nieczytelna wartość → „—”. */
export function formatRateNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = Math.round(Math.abs(value) * 1000) % 10 === 0 ? RATE_2 : RATE_3;
  return digits.format(value);
}

/**
 * Kwota miesięczna w pełnych jednostkach z odstępem co trzy cyfry także przy
 * czterech („6 384”; `Intl` dla pl-PL grupuje dopiero od pięciu). Odstęp jest
 * twardą spacją, żeby kwota nie łamała się między wierszami.
 */
export function formatWholeAmount(value: number): string {
  const rounded = Math.round(value);
  const digits = String(Math.abs(rounded)).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
  return `${rounded < 0 ? "-" : ""}${digits}`;
}

/** „23,3 %”. */
export function formatPercent(value: number): string {
  return `${PERCENT.format(value)}\u00a0%`;
}

/** Waluta i jednostka stawki kontraktu: „zł/h”, „EUR/h”, „zł/MD”, „zł/mc”. */
export function rateUnitLabel(currency: string | null | undefined, rateUnit: string): string {
  return `${currencySymbol(currency)}${rateUnitSuffix(rateUnit)}`;
}

/** Przeliczenie na złote z kursu NBP: „166,68 zł”. */
export function formatPlnAmount(amount: number): string {
  return `${RATE_2.format(amount)} zł`;
}

/** Kurs NBP z czterema miejscami: „4,3014 zł”. */
export function formatNbpRate(rate: number): string {
  return `${NBP_RATE.format(rate)} zł`;
}

/** Data tabeli NBP: „25.08.2026”. */
export function formatNbpDate(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return formatIsoDatePl(date);
  return `${match[3]}.${match[2]}.${match[1]}`;
}
