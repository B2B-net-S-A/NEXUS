/**
 * Data w formacie DD.MM.RRRR — z zerem wiodącym w dniu i miesiącu.
 *
 * `Intl.DateTimeFormat("pl-PL")` daje „3.09.2026" (dzień bez zera), a surowa
 * wartość z API „2026-09-03". Obok siebie na jednym ekranie czytały się jak
 * dwa różne formaty. Data kalendarzowa `RRRR-MM-DD` jest składana z cyfr, BEZ
 * `new Date(...)`: tamto liczy północ UTC i w strefie za UTC cofa dzień.
 * Wartość z czasem (`created_at`) idzie przez lokalną datę przeglądarki.
 */
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export function formatIsoDatePl(value: string | null | undefined): string {
  if (!value) return "—";
  const match = DATE_ONLY.exec(value.trim());
  if (match) return `${match[3]}.${match[2]}.${match[1]}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`;
}

/** „DD.MM.RRRR GG:MM" w lokalnej strefie przeglądarki. */
export function formatDateTimePl(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
