/**
 * Ochrona komórek CSV/XLSX budowanych W PRZEGLĄDARCE przed wstrzyknięciem
 * formuły (runda 6 audytu) — lustro `backend/app/core/export_safety.safe_cell`.
 *
 * Tekst zaczynający się od `= + - @`, tabulatora albo powrotu karetki Excel
 * i LibreOffice czytają jako formułę (`=HYPERLINK(…)` w nazwisku zamienia
 * plik w link do cudzego serwera), więc dostaje prefiks `'`. Wyjątek jak
 * w backendzie: same cyfry i separatory („+48 600 100 200”, „-1 200,50”) nie
 * wywołają funkcji, a apostrof psułby kolumnę telefonu. Liczby i puste
 * wartości przechodzą bez zmian.
 */

const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"] as const;
const NUMBER_LIKE = /^[+-][\d\s().,/-]*\d[\d\s().,/-]*$/;

export function safeSpreadsheetCell<T>(value: T): T | string {
  if (typeof value !== "string") return value;
  if (!FORMULA_PREFIXES.some((prefix) => value.startsWith(prefix))) return value;
  if (NUMBER_LIKE.test(value)) return value;
  return `'${value}`;
}
