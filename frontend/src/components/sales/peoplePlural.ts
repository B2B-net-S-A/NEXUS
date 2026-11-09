/** Odmiana po liczbie: 1 osoba, 2 osoby, 5 osób, 12 osób, 22 osoby. */
export function plural(count: number, one: string, few: string, many: string): string {
  if (count === 1) return one;
  const tens = count % 100;
  const units = count % 10;
  return units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many;
}
