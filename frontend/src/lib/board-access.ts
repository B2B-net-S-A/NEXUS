/**
 * Rola „Rada nadzorcza” (0490, decyzja Artura 21.10.2026) — jeden ekran:
 * Insights, domyślnie widok Firma. Wspólne dla middleware (Edge, bez store'a)
 * i lądowania po zalogowaniu (`postLoginDestination`).
 */

/** Dom Rady nadzorczej: Insights → Firma. */
export const BOARD_HOME = "/insights?tab=firma"

/** Ekrany Rady: Insights, własne konto (hasło, powiadomienia) i Pomoc.
 *  Reszta odbija na {@link BOARD_HOME}, nie na /403 — Rada nie ma „reszty
 *  aplikacji”, do której mogłaby trafić przez pomyłkę. */
export function isBoardAllowedPath(pathname: string): boolean {
  return (
    pathname === "/insights" ||
    pathname.startsWith("/insights/") ||
    pathname === "/profile" ||
    pathname.startsWith("/profile/") ||
    pathname === "/settings" ||
    pathname === "/help" ||
    pathname.startsWith("/help/")
  )
}
