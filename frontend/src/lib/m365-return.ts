/**
 * Powrót z logowania Microsoft na ekran, z którego zaczęło się podłączanie.
 *
 * Callback backendu zawsze kieruje na `/microsoft365/callback`, a ta strona
 * domyślnie wraca do Ustawień. Handlowiec podłącza skrzynkę w Sprzedaży
 * (28.10.2026), więc tam ma wrócić. Tylko ścieżki wewnętrzne z listy — adres
 * w `sessionStorage` nie może przekierować poza NEXUSA.
 */
const KEY = "m365_return_to";
const ALLOWED_PREFIXES = ["/sales"];

export function isAllowedReturnPath(path: string | null | undefined): path is string {
  if (!path || !path.startsWith("/") || path.startsWith("//")) return false;
  return ALLOWED_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}

export function rememberM365Return(path: string): void {
  if (!isAllowedReturnPath(path)) return;
  try {
    window.sessionStorage.setItem(KEY, path);
  } catch {
    // Prywatne okno bez sessionStorage — wrócimy do Ustawień.
  }
}

/** Odczytuje i czyści zapamiętaną ścieżkę; bez niej — Ustawienia. */
export function takeM365Return(fallback = "/settings"): string {
  try {
    const path = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    return isAllowedReturnPath(path) ? path : fallback;
  } catch {
    return fallback;
  }
}
