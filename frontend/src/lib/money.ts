/**
 * Kwota + waluta + jednostka stawki — jeden format dla Klientów, Kontraktów i Finansów.
 *
 * Do 24.09.2026 kwoty formatowało 9 funkcji, a tę samą jednostkę opisywały
 * sufiksy „/MD”, „/dz.”, „dzień” i „/dz”; skrzynka zamówień pokazywała EUR
 * jako złote. Reguły:
 * - PLN wyświetla się jako „zł”, inne waluty kodem ISO („EUR”);
 * - zawsze 2 miejsca po przecinku, chyba że kwota ma ich więcej (stawki
 *   kontraktu po przeliczeniu MD ÷ 8 niosą do 6) — wtedy do 3;
 * - jednostka stawki zawsze jednym słownikiem: /h, /MD, /mc.
 */

export type MoneyUnit =
  | "hour"
  | "hourly"
  | "h"
  | "day"
  | "daily"
  | "md"
  | "MD"
  | "month"
  | "monthly"
  | "mc";

const UNIT_SUFFIX: Record<string, string> = {
  hour: "/h",
  hourly: "/h",
  h: "/h",
  day: "/MD",
  daily: "/MD",
  md: "/MD",
  MD: "/MD",
  month: "/mc",
  monthly: "/mc",
  mc: "/mc",
};

/** Sufiks jednostki stawki („/h”, „/MD”, „/mc”); nieznana jednostka → "". */
export function rateUnitSuffix(unit: string | null | undefined): string {
  if (!unit) return "";
  return UNIT_SUFFIX[unit] ?? "";
}

/** „zł” dla PLN (i braku waluty), kod ISO dla pozostałych. */
export function currencySymbol(currency: string | null | undefined): string {
  const code = (currency || "PLN").toUpperCase();
  return code === "PLN" ? "zł" : code;
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function fractionDigits(n: number): number {
  const scaled = Math.round(Math.abs(n) * 1000);
  return scaled % 10 === 0 ? 2 : 3;
}

/**
 * „1 234,50 zł”, „250,00 EUR”, z jednostką: „1 050,00 zł/MD”.
 * Pusta albo nieczytelna kwota → „—” (nigdy „0 zł”).
 */
export function formatMoney(
  value: number | string | null | undefined,
  currency?: string | null,
  unit?: string | null,
): string {
  const n = toNumber(value);
  if (n == null) return "—";
  const digits = fractionDigits(n);
  const amount = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
  return `${amount} ${currencySymbol(currency)}${rateUnitSuffix(unit)}`;
}
