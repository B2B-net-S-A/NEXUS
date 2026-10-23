/**
 * Rola „Rada nadzorcza” (0490, decyzja Artura 21.10.2026) — Insights,
 * domyślnie widok Firma, a od 23.10.2026 także lista „Umowy przedwstępne”.
 * Wspólne dla middleware (Edge, bez store'a) i lądowania po zalogowaniu
 * (`postLoginDestination`).
 */

import { PRE_CONTRACTS_PATH } from "@/lib/pre-contract-access"

/** Dom Rady nadzorczej: Insights → Firma. */
export const BOARD_HOME = "/insights?tab=firma"

/** Ekrany Rady: Insights, własne konto (hasło, powiadomienia), Pomoc i sama
 *  lista „Umowy przedwstępne” (decyzja Artura 23.10.2026 — panel osoby i reszta
 *  rekrutacji zostają zamknięte). Reszta odbija na {@link BOARD_HOME}, nie na
 *  /403 — Rada nie ma „reszty aplikacji”, do której mogłaby trafić przez
 *  pomyłkę. */
export function isBoardAllowedPath(pathname: string): boolean {
  return (
    pathname === PRE_CONTRACTS_PATH ||
    pathname === "/insights" ||
    pathname.startsWith("/insights/") ||
    pathname === "/profile" ||
    pathname.startsWith("/profile/") ||
    pathname === "/settings" ||
    pathname === "/help" ||
    pathname.startsWith("/help/")
  )
}
