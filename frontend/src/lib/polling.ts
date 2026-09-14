/**
 * Jedno miejsce dla interwałów odpytywania w tle.
 *
 * Powód (audyt 13.09.2026): sam otwarty dashboard generował ~9,5 GET/min na
 * kartę bez klikania (dzwonek co 30 s, KPI co 60 s, cztery sekcje dashboardu
 * co 60 s, onboarding co 30 s). Przy 50 kartach to ~8 RPS ruchu tła, przy 100
 * ~16 RPS — zanim ktokolwiek cokolwiek zrobi. WebSocket i tak inwaliduje
 * powiadomienia i KPI na zdarzeniach, więc interwały są tylko siatką
 * bezpieczeństwa i mogą być rzadkie. `refetchIntervalInBackground` zostaje
 * domyślne (false): ukryta karta nie odpytuje wcale.
 *
 * Zmieniając wartość, zmień ją TUTAJ — komponenty importują stałe, nie liczby.
 */

/** Siatka bezpieczeństwa dla danych, które WebSocket odświeża na zdarzeniach. */
export const WS_BACKED_SAFETY_POLL_MS = 5 * 60_000;

/** Powiadomienia, gdy WebSocket jest rozłączony (jedyne źródło świeżości). */
export const NOTIFICATIONS_FALLBACK_POLL_MS = 60_000;

/** Finanse → Zmiany w zamówieniach: siatka pod odświeżeniem przy powrocie do karty. */
export const ORDER_CHANGES_POLL_MS = 5 * 60_000;

/** Sekcje dashboardu (aktywność, rekrutacje, zadania, onboarding). */
export const DASHBOARD_SECTION_POLL_MS = 5 * 60_000;

/** Obłożenie zespołu w priorytetach — zmienia się przy ruchu w pipeline. */
export const ALLOCATION_BOARD_POLL_MS = 2 * 60_000;
