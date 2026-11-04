import Decimal from "decimal.js";

import {
  HOURS_PER_MD as WORK_HOURS_PER_MD,
  MD_PER_MONTH as WORK_MD_PER_MONTH,
} from "@/lib/work-time";

/**
 * Przelicznik jednostki stawki: godzinowa / miesięczna ↔ MD.
 *
 * Moduł zamówień MD rozlicza się WYŁĄCZNIE w zł/MD (`md_rate_cost`,
 * `md_rate_revenue` — patrz CLAUDE.md), a stawki przychodzą z dwóch źródeł:
 * z kontraktu (godzinowa, dzienna lub miesięczna) i z zamówienia klienta (MD).
 * Przełącznik pozwala wpisać to, co operator ma przed sobą, ale ZAPISYWANA
 * wartość jest zawsze w jednostce rozliczeniowej modułu — przeliczenie jest
 * wyłącznie warstwą wprowadzania danych.
 *
 * Wyniesione z komponentu, żeby regułę dało się przetestować bez montowania
 * modala — i żeby druga powierzchnia, która tego zechce, nie dopisała drugiej
 * kopii mnożnika.
 */

/** Roboczodzień (MD) = 8 godzin. Ta sama stała co po stronie parsera PDF. */
export const HOURS_PER_MD = WORK_HOURS_PER_MD;
/** Standardowy miesiąc roboczy (21 MD, `lib/work-time.ts`; do 22.09.2026: 22). */
export const MD_PER_MONTH = WORK_MD_PER_MONTH;

export type RateUnit = "hour" | "md" | "month";
export type ContractRateUnit = "hourly" | "daily" | "monthly";

/** Etykiety bazowe; komponent dokłada kod rzeczywistej waluty. */
export const RATE_UNIT_LABELS: Record<RateUnit, string> = {
  hour: "godzinowa",
  md: "MD 8h",
  month: "miesięczna",
};

export function rateUnitLabel(unit: RateUnit, currency = "PLN"): string {
  const suffix = unit === "hour" ? "h" : unit === "md" ? "MD" : "mc";
  const currencyLabel = currency === "PLN" ? "zł" : currency;
  return `${RATE_UNIT_LABELS[unit]} (${currencyLabel}/${suffix})`;
}

/**
 * Kontrakt dzienny i linia zamówienia MD opisują tę samą jednostkę biznesową.
 * Brak jednostki oznacza stary payload API, który zawsze niósł już PLN/MD.
 */
export function contractRateUnitToInputUnit(
  unit?: ContractRateUnit | null,
): RateUnit {
  if (unit === "hourly") return "hour";
  if (unit === "monthly") return "month";
  return "md";
}

/**
 * Przelicz kwotę między jednostkami. Zwraca `null` dla wejścia, którego nie da
 * się przeliczyć (NaN/Infinity) — wołający zostawia wtedy pole nietknięte
 * zamiast wpisywać do niego „NaN”.
 */
export function convertRate(
  value: number,
  from: RateUnit,
  to: RateUnit,
): number | null {
  if (!Number.isFinite(value)) return null;
  if (from === to) return decimalToMoney(new Decimal(value));
  const md = toMdDecimal(value, from);
  return decimalToMoney(fromMdDecimal(md, to));
}

/**
 * Stawki linii zamówienia MD mają TRZY miejsca po przecinku (kolumny
 * `md_rate_*` = Numeric(12,3) od migracji 0419). Przeliczenie 291 zł/MD → zł/h
 * daje 36,375 — dwa miejsca pokazywały „36.38”, a zapis z powrotem ×8 dawał
 * 291,04 zamiast 291.
 */
export const RATE_DECIMALS = 3;

function decimalToMoney(value: Decimal): number {
  return value.toDecimalPlaces(RATE_DECIMALS, Decimal.ROUND_HALF_UP).toNumber();
}

/**
 * Wartość pola stawki: zawsze trzy miejsca po przecinku („36.375”, „1000.000”).
 * Pole wstawione przez program (podpowiedź, przeliczenie jednostki, odczyt
 * PDF) i pole po opuszczeniu go przez operatora wyglądają tak samo — bez tego
 * jedna stawka miała dwa miejsca, druga żadnego. Pusta / niepoprawna = „”.
 */
export function formatRateField(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "";
  // API bywa, że serializuje Decimal jako tekst („1300.000000”).
  const parsed = typeof value === "string" ? Number.parseFloat(value) : value;
  if (!Number.isFinite(parsed)) return "";
  return new Decimal(parsed).toFixed(RATE_DECIMALS, Decimal.ROUND_HALF_UP);
}

/**
 * Stawka KONTRAKTU do pola linii: w jej własnej jednostce, gdy mieści się
 * w trzech miejscach; inaczej od razu w MD. Kontrakt trzyma 6 miejsc
 * (1001,55 zł/MD = 125,19375 zł/h) — pole z „125.194” zapisałoby ×8 jako
 * 1001,552, czyli nie stawkę z kontraktu.
 */
export function contractRateField(
  value: number | null | undefined,
  unit: RateUnit,
): { value: string; unit: RateUnit } {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return { value: "", unit };
  }
  if (new Decimal(value).decimalPlaces() <= RATE_DECIMALS || unit === "md") {
    return { value: formatRateField(value), unit };
  }
  return { value: formatRateField(toMdRate(value, unit)), unit: "md" };
}

/** Tekst pola po opuszczeniu go: liczba → trzy miejsca, reszta bez zmian. */
export function normalizeRateField(raw: string): string {
  const normalized = raw.trim().replace(",", ".");
  if (normalized === "") return "";
  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? formatRateField(parsed) : raw;
}

function toMdDecimal(value: number, unit: RateUnit): Decimal {
  const rate = new Decimal(value);
  if (unit === "hour") return rate.times(HOURS_PER_MD);
  if (unit === "month") return rate.dividedBy(MD_PER_MONTH);
  return rate;
}

function fromMdDecimal(value: Decimal, unit: RateUnit): Decimal {
  if (unit === "hour") return value.dividedBy(HOURS_PER_MD);
  if (unit === "month") return value.times(MD_PER_MONTH);
  return value;
}

/**
 * Wartość do ZAPISU — zawsze w zł/MD, niezależnie od wybranej jednostki.
 *
 * To jest jedyne miejsce, które wie, że baza mówi w MD. Gdyby przeliczenie
 * zostało w komponencie, przełącznik ustawiony na „godzinowa” zapisywałby
 * stawkę godzinową do kolumny opisanej jako MD — błąd cichy i ośmiokrotny.
 */
export function toMdRate(value: number, unit: RateUnit): number | null {
  if (!Number.isFinite(value)) return null;
  return decimalToMoney(toMdDecimal(value, unit));
}

/**
 * Kanoniczna wartość kosztu linii: PLN/MD. Kurs stosujemy przed końcowym
 * zaokrągleniem, żeby np. stawka miesięczna w EUR nie traciła groszy przez
 * pośrednie zaokrąglenie EUR/MD.
 */
export function toPlnMdRate(
  value: number,
  unit: RateUnit,
  rateToPln: number,
): number | null {
  if (!Number.isFinite(value) || !Number.isFinite(rateToPln) || rateToPln <= 0) {
    return null;
  }
  return decimalToMoney(toMdDecimal(value, unit).times(rateToPln));
}

/**
 * Sufiks jednostki stawki KONTRAKTU do wyświetlenia obok kwoty („/h", „/MD",
 * „/mc"). Od synchronizacji kontrakt ↔ zamówienia (09.2026) kontrakt zmienia
 * jednostkę razem z zamówieniem (120 zł/h → 960 zł/MD), więc kwota bez
 * jednostki w rejestrze przestała cokolwiek znaczyć.
 */
export function contractRateUnitSuffix(
  unit?: ContractRateUnit | string | null,
): string {
  if (unit === "hourly") return "/h";
  if (unit === "daily") return "/MD";
  if (unit === "monthly") return "/mc";
  return "";
}
