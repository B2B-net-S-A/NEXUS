import Decimal from "decimal.js";

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
export const HOURS_PER_MD = 8;
/** Standardowy miesiąc rozliczeniowy kontraktu miesięcznego. */
export const MD_PER_MONTH = 22;

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
 * Zaokrąglenie do 2 miejsc, half-up, ODPORNE na błąd binarny.
 *
 * `Math.round(x * 100) / 100` gubi się na wartościach, których zapis
 * zmiennoprzecinkowy leży minimalnie poniżej połowy (klasyczne 1.005 → 1),
 * a tutaj chodzi o kwoty widoczne obok siebie w dwóch jednostkach: operator
 * natychmiast zauważy, że ×8 i ÷8 nie wracają do tej samej liczby.
 */
export function roundTo2(value: number): number {
  if (!Number.isFinite(value)) return NaN;
  return new Decimal(value)
    .toDecimalPlaces(2, Decimal.ROUND_HALF_UP)
    .toNumber();
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
  if (from === to) return roundTo2(value);
  const md = toMdDecimal(value, from);
  return decimalToMoney(fromMdDecimal(md, to));
}

function decimalToMoney(value: Decimal): number {
  return value.toDecimalPlaces(2, Decimal.ROUND_HALF_UP).toNumber();
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
