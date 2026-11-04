import { safeInternalPath } from "@/lib/safe-href";

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

/**
 * Dokąd wrócić po logowaniu Microsoft (runda 10, R10-N15-1).
 *
 * `?next=` z /login nie przeżywa przekierowania do Microsoftu (callback ma
 * własny adres), więc na produkcji — SSO-only — link z maila albo dzwonka
 * kończył się na pulpicie. Ścieżka jest sprawdzana przy zapisie i przy
 * odczycie (`safeInternalPath`), bo sessionStorage to też dane z zewnątrz.
 */
const NEXT_KEY = "nexus_sso_next_path";

export function saveSsoNextPath(next: string | null | undefined): void {
  try {
    const safe = safeInternalPath(next);
    if (safe && safe !== "/") window.sessionStorage.setItem(NEXT_KEY, safe);
    else window.sessionStorage.removeItem(NEXT_KEY);
  } catch {
    // Zablokowane dane witryny — po logowaniu trafimy na pulpit.
  }
}

export function takeSsoNextPath(): string | null {
  try {
    const value = window.sessionStorage.getItem(NEXT_KEY);
    window.sessionStorage.removeItem(NEXT_KEY);
    return safeInternalPath(value);
  } catch {
    return null;
  }
}
