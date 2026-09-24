/**
 * Które pliki wolno otworzyć w nowej karcie jako `blob:` URL.
 *
 * Blob ma ORIGIN APLIKACJI — dokument HTML/SVG/XML otwarty z bloba wykonuje
 * skrypty z dostępem do `localStorage` (token sesji). Typ pliku bierze się
 * z nagłówka, który wysłał wgrywający (dokumenty kontraktu, PO zamówień), więc
 * `raport.pdf` zadeklarowany jako `text/html` otwierał się jako strona
 * (audyt bezpieczeństwa 24.09.2026). Inline wyłącznie PDF i obrazy rastrowe;
 * każdy inny typ — także nieznany — idzie do pobrania.
 */

const INLINE_SAFE_TYPES = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
]);

/** Typ do otwarcia inline albo `null`, gdy plik trzeba pobrać. */
export function inlineSafeType(
  declared: string | null | undefined,
  fromResponse?: string | null,
): string | null {
  const raw = (declared || fromResponse || "").split(";")[0].trim().toLowerCase();
  return INLINE_SAFE_TYPES.has(raw) ? raw : null;
}
