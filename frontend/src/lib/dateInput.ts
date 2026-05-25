export const DATE_PLACEHOLDER = "RRRR-MM-DD lub DD.MM.RRRR";
export const DATE_PATTERN =
  "\\d{4}-\\d{1,2}-\\d{1,2}|\\d{1,2}[./-]\\d{1,2}[./-]\\d{4}";

export function normalizeDateInput(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  const iso = trimmed.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (iso) {
    const [, y, m, d] = iso;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  const eu = trimmed.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/);
  if (eu) {
    const [, d, m, y] = eu;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  return trimmed;
}
