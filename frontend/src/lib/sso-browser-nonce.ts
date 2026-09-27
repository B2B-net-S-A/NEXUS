/**
 * Sekret karty, która zaczęła logowanie Microsoft (runda 9, R9-N1-4).
 *
 * `/api/auth/microsoft/authorize` wydaje `browser_nonce`; trzymamy go
 * w sessionStorage tej karty i odsyłamy przy `/exchange`. Kod wymiany
 * z cudzego logowania (link podrzucony w mailu — login CSRF) bez tego
 * sekretu nie działa, więc nikt nie zaloguje nas na swoje konto.
 * sessionStorage, nie localStorage: sekret ma żyć tyle, co ta jedna próba.
 */
const KEY = "nexus_sso_browser_nonce";

export function saveSsoBrowserNonce(nonce: string | undefined | null): void {
  try {
    if (nonce) window.sessionStorage.setItem(KEY, nonce);
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // Zablokowane dane witryny — wymiana i tak się nie uda; komunikat da backend.
  }
}

export function takeSsoBrowserNonce(): string | null {
  try {
    const value = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    return value;
  } catch {
    return null;
  }
}
