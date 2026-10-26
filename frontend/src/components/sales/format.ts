// Sprzedaż — formaty kwot i dat w kartach i na tablicy.

import { currencySymbol } from "@/lib/money";

/** „45 000” — wartość szansy bez groszy i waluty (jednostka w nagłówku kolumny). */
export function formatDealNumber(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 }).format(n);
}

/** „45 000 zł” — wartości szans bez groszy (wycena, nie faktura). Pusta → „—”. */
export function formatDealAmount(
  value: string | number | null | undefined,
  currency = "PLN",
): string {
  const amount = formatDealNumber(value);
  return amount === "—" ? amount : `${amount} ${currencySymbol(currency)}`;
}

/** Dni od chwili ISO do teraz (zaokrąglone w dół), `null` dla braku daty. */
export function daysSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return null;
  return Math.max(0, Math.floor((now - at) / 86_400_000));
}

/** „dziś”, „1 dzień”, „5 dni”. */
export function daysLabel(days: number): string {
  if (days === 0) return "dziś";
  return days === 1 ? "1 dzień" : `${days} dni`;
}
