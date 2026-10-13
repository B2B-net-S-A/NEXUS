/**
 * Pobierania i zapisy idące zwykłym `fetch`, nie przez `api` (ZIP z CV, eksport
 * XLSX, pliki z `authenticated-files`) — interceptory ich nie widzą, a
 * przeładowanie przy nowej wersji frontu przerwałoby plik (audyt 13.10.2026).
 * Czyta to `AppVersionGuard`; moduł, nie stan komponentu, bo wołają go funkcje
 * spoza drzewa React.
 */
let inFlight = 0;

/** Owija pracę na zwykłym `fetch`. Licznik schodzi także po błędzie. */
export async function trackTransfer<T>(work: () => Promise<T>): Promise<T> {
  inFlight += 1;
  try {
    return await work();
  } finally {
    inFlight = Math.max(0, inFlight - 1);
  }
}

export function transfersInFlight(): number {
  return inFlight;
}
