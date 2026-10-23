/**
 * Sufit czasu dla interaktywnych wywołań LLM / scoringu / generacji.
 *
 * Domyślny timeout instancji `api` (30 s, `lib/api.ts`) jest skrojony pod
 * CRUD-y. Wywołania, po których drugiej stronie liczy model, mieszczą się
 * w nim tylko czasem: parse profilu Championa zmierzono na 10-31+ s, a
 * scoring na zimnym cache przekracza 30 s regularnie — dlatego #1210 i #1211
 * podnosiły sufit najpierw w samym radarze, zanim stał się wspólny.
 *
 * Skutek za niskiego timeoutu jest gorszy niż czekanie: przeglądarka zrywa
 * połączenie, backend kończy generację i PŁACI za nią, a użytkownik widzi
 * błąd i klika „odśwież" — czyli mnoży ten koszt. 120 s pokrywa zmierzony
 * ogon z zapasem.
 *
 * Świadomie NIE dotyczy importów, backfillów i zadań administracyjnych: tam
 * nikt nie siedzi przy ekranie, a dłuższy timeout tylko odsuwa moment, w
 * którym widać, że zadanie utknęło.
 */
export const SLOW_ENDPOINT_TIMEOUT_MS = 120_000;

/**
 * Timeout po stronie PRZEGLĄDARKI (sufit instancji albo per-request
 * `SLOW_ENDPOINT_TIMEOUT_MS`). Żądanie dotarło i backend nadal je liczy —
 * powtórka nie skraca oczekiwania, tylko mnoży pracę i koszt modelu. Tu, a nie
 * w `lib/api.ts`, bo okna pokazują po nim osobny komunikat, a ich testy
 * podmieniają cały `@/lib/api`.
 */
export function isClientTimeout(err: unknown): boolean {
  const code = (err as { code?: unknown } | null | undefined)?.code;
  return code === "ECONNABORTED" || code === "ETIMEDOUT";
}

/**
 * Sufit czasu dla żądań z plikiem (`FormData`), które nie podają własnego
 * `timeout`. Ustawia go interceptor żądań w `lib/api.ts` — jedno miejsce
 * zamiast poprawiania ~30 wywołań po kolei.
 *
 * 30 s instancji to czas na odpowiedź CRUD-a, a tu zegar tyka już w trakcie
 * WYSYŁANIA pliku: skan do 25 MB przy 1–2 Mbit/s wysyłki to 100–200 s. Po
 * przekroczeniu przeglądarka zrywa wysyłkę (`ECONNABORTED`), uvicorn nie
 * loguje przerwanego uploadu, więc w logach backendu nie ma żadnego POST-a,
 * a ekran pokazuje ogólne „Nie udało się…” (umowa ramowa Anny 23.10.2026,
 * #2640). 300 s pokrywa 25 MB przy 1 Mbit/s z zapasem na zapis po stronie
 * serwera; dłużej nikt nie czeka przy ekranie.
 */
export const FILE_UPLOAD_TIMEOUT_MS = 300_000;
