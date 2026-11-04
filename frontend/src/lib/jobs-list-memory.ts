/**
 * Pamięć ostatniego widoku listy rekrutacji (13.10.2026): zakres, sortowanie,
 * stan requestu, filtry paska i przełączniki — per osoba, w przeglądarce.
 * Goły `/jobs` (menu, okruszek, kafel pulpitu) otwiera ten widok; link
 * z parametrami wygrywa. Szukajki i numeru strony tu nie ma.
 *
 * Wpis przeżywa wylogowanie (klucz poza prefiksami z `lib/session.ts`, jak
 * `new-job-leads-filters.ts`): to ustawienie widoku osoby, a wartością są
 * same klucze i identyfikatory filtrów. Pamięć jest wygodą, nie źródłem
 * prawdy — każdy odczyt i zapis jest w try/catch, lista działa bez niej.
 */

import { hasJobsListParams } from "./jobs-url-filters";

type UserId = number | string | null | undefined;

/** Klucz wpisu osoby; brak id = brak pamięci. */
export function jobsListMemoryKey(userId: UserId): string | null {
  return userId == null ? null : `nexus:jobs-list-filters:${userId}`;
}

/**
 * Zapamiętany widok jako parametry listy. Czytają je te same parsery co adres
 * (`initial*FromUrl`), więc zepsuta wartość znaczy „bez zawężenia”, nie błąd.
 */
export function readJobsListMemory(key: string | null): URLSearchParams | null {
  if (!key) return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const params = new URLSearchParams(raw);
    params.delete("q");
    return hasJobsListParams(params) ? params : null;
  } catch {
    return null;
  }
}

/** Widok z samymi wartościami domyślnymi (pusty napis) usuwa wpis. */
export function writeJobsListMemory(key: string | null, query: string): void {
  if (!key) return;
  try {
    if (query) window.localStorage.setItem(key, query);
    else window.localStorage.removeItem(key);
  } catch {
    /* pełna albo zablokowana pamięć — lista działa bez niej */
  }
}
