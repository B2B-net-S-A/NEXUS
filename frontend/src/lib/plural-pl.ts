/**
 * Polska liczba mnoga — TRZY formy, nie dwie.
 *
 * Wzorzec `n === 1 ? "zamówienie" : "zamówienia"` daje „0 zamówienia"
 * i „5 zamówienia" — obie niepoprawne. Polski wymaga:
 *
 *   1                        → zamówieni**e**   (mianownik)
 *   2–4, 22–24, 32–34, …     → zamówieni**a**   (mianownik mnogi)
 *   0, 5–21, 25–31, …        → zamówie**ń**     (dopełniacz mnogi)
 *
 * Wyjątek na 12–14 jest istotny: „12" kończy się na „2", ale bierze formę
 * dopełniacza („12 zamówień", nie „12 zamówienia").
 */
export function pluralPl(
  count: number,
  one: string,
  few: string,
  many: string,
): string {
  const n = Math.abs(Math.trunc(count));
  if (n === 1) return one;
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return few;
  return many;
}

/** `pluralPl` z liczbą z przodu — najczęstszy przypadek użycia. */
export function countPl(
  count: number,
  one: string,
  few: string,
  many: string,
): string {
  return `${count} ${pluralPl(count, one, few, many)}`;
}
