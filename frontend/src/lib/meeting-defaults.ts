/**
 * Domyślne okno spotkania w szybkim planowaniu („+ Dodaj → Zaplanuj
 * spotkanie"): początek o najbliższej PEŁNEJ godzinie, koniec godzinę później.
 *
 * Arytmetyka idzie przez `Date`, a nie przez `getHours() + 1` wklejone do
 * napisu — po 22:00 tamto dawało „T24:00", po 23:00 „T25:00", a
 * `new Date("…T25:00").toISOString()` rzucało „Invalid time value" przed
 * wysłaniem formularza (FE-12). `Date` przewija dzień, miesiąc i rok sam.
 */

const pad = (n: number): string => String(n).padStart(2, "0");

/** Lokalny czas w formacie `<input type="datetime-local">`: `YYYY-MM-DDTHH:mm`. */
export function toDatetimeLocalValue(date: Date): string {
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function defaultMeetingWindow(now: Date = new Date()): {
  start: string;
  end: string;
} {
  const start = new Date(now.getTime());
  start.setMinutes(0, 0, 0);
  start.setHours(start.getHours() + 1);
  const end = new Date(start.getTime());
  end.setHours(end.getHours() + 1);
  return { start: toDatetimeLocalValue(start), end: toDatetimeLocalValue(end) };
}
