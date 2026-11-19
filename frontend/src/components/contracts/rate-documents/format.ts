const MONTHS = [
  "01",
  "02",
  "03",
  "04",
  "05",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
];

/** „01.11.2026” z ISO. */
export function dayPl(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** „11.2026” z ISO — miesiąc, od którego zmienia się stawka. */
export function monthPl(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m] = iso.slice(0, 10).split("-");
  return `${MONTHS[Number(m) - 1] ?? m}.${y}`;
}

/** „124 zł/h”, „148,40 zł/h”. */
export function ratePl(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const text = Number.isInteger(value)
    ? String(value)
    : value.toFixed(2).replace(".", ",");
  return `${text} zł/h`;
}
