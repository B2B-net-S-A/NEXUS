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
