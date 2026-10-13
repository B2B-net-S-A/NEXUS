/**
 * Układ podglądu w rozwiniętym panelu osoby (13.10.2026, zgłoszenie
 * rekrutera): czy CV i kolumna z wymaganiami są zwinięte — per osoba,
 * w przeglądarce.
 *
 * Rekruter, który woli szerokie CV, nie zwija wymagań przy każdym kandydacie
 * (decyzja D4). Wpis przeżywa wylogowanie (klucz poza prefiksami
 * z `lib/session.ts`, jak `jobs-list-memory.ts`): to ustawienie widoku, bez
 * danych. Pamięć jest wygodą — każdy odczyt i zapis jest w try/catch, panel
 * działa bez niej w układzie domyślnym.
 */

type UserId = number | string | null | undefined;

export interface PersonPreviewLayout {
  /** CV zwinięte do listwy przy lewej krawędzi. */
  cvCollapsed: boolean;
  /** Kolumna o rekrutacji (wymagania, warunki, „Po ludzku”) zwinięta do paska nad CV. */
  infoCollapsed: boolean;
}

export const DEFAULT_PERSON_PREVIEW_LAYOUT: PersonPreviewLayout = Object.freeze({
  cvCollapsed: false,
  infoCollapsed: false,
});

/** Klucz wpisu osoby; brak id = brak pamięci. */
export function personPreviewLayoutKey(userId: UserId): string | null {
  return userId == null ? null : `nexus:person-preview-layout:${userId}`;
}

/** Zapamiętany układ; pole spoza `true`/`false` znaczy „otwarte”. */
export function readPersonPreviewLayout(key: string | null): PersonPreviewLayout {
  if (!key) return DEFAULT_PERSON_PREVIEW_LAYOUT;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return DEFAULT_PERSON_PREVIEW_LAYOUT;
    const parsed: unknown = JSON.parse(raw);
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) return DEFAULT_PERSON_PREVIEW_LAYOUT;
    const value = parsed as Record<string, unknown>;
    return {
      cvCollapsed: value.cvCollapsed === true,
      infoCollapsed: value.infoCollapsed === true,
    };
  } catch {
    return DEFAULT_PERSON_PREVIEW_LAYOUT;
  }
}

export function writePersonPreviewLayout(key: string | null, layout: PersonPreviewLayout): void {
  if (!key) return;
  try {
    window.localStorage.setItem(key, JSON.stringify(layout));
  } catch {
    /* pełna albo zablokowana pamięć — panel działa bez niej */
  }
}
