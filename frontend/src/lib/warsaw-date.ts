/**
 * Data „dziś" w kalendarzu firmy (Europe/Warsaw), jako "YYYY-MM-DD".
 *
 * `new Date().toISOString().slice(0, 10)` daje datę UTC: między północą
 * w Warszawie a północą UTC (1–2 h na dobę) wychodzi WCZORAJ. Formularz
 * aneksu otwarty o 00:30 podpowiadał więc wczorajszą datę wejścia w życie,
 * a zwrot sprzętu zapisywał się dniem wcześniej. Backend liczy „dziś"
 * tak samo (`business_today()`), więc obie strony mówią o tym samym dniu.
 *
 * `now` jest parametrem wyłącznie dla testów.
 */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Dzień kalendarza firmy („YYYY-MM-DD”, Europe/Warsaw) znacznika czasu z API.
 *
 * Runda 10 (R10-X1-3): `created_at.slice(0, 10)` bierze dzień UTC, więc
 * zdarzenie z 00:00–02:00 w Warszawie pokazywało się z datą dnia
 * poprzedniego. Sama data (`RRRR-MM-DD`) wraca bez zmian; wartość
 * nieczytelna — `null`.
 */
export function warsawDateOf(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (DATE_ONLY.test(trimmed)) return trimmed;
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return null;
  return warsawToday(date);
}
