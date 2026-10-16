/**
 * Pamięć niezapisanej rozmowy screeningowej w karcie przeglądarki — per osoba
 * pisząca i kandydat (16.10.2026, decyzja Artura D3 B). Przeżywa zamknięcie
 * panelu osoby, kliknięcie innej osoby na Tablicy i odświeżenie strony; znika
 * przy zapisie formularza, „Odrzuć szkic” albo po 12 h bez zmian.
 *
 * `sessionStorage`, świadomie NIE `localStorage` — ten sam powód co szkic
 * notatki (lib/note-drafts.ts): odpowiedzi i stawka kandydata żyją najwyżej
 * tyle co karta przeglądarki, a wylogowanie kasuje je wprost
 * (`clearSessionArtifacts` w lib/session.ts woła `clearScreeningMemories`).
 *
 * Moduł bez importów w czasie wykonania (lib/session.ts go importuje). Pamięć
 * przeglądarki bywa zablokowana: wtedy formularz pamięta rozmowę tylko do
 * przeładowania strony, funkcje nigdy nie rzucają. Kształt wpisu opisuje
 * lib/screening-memory.ts — tu tylko zapis, odczyt i wygasanie.
 */

const PREFIX = "nexus:screening-memory:v1:";

/** Pamięć bez zmian dłużej niż 12 h wygasa — jak rezerwacja osoby. */
export const SCREENING_MEMORY_TTL_MS = 12 * 60 * 60 * 1000;

function storageKey(userId: number | undefined, candidateId: number): string | null {
  if (userId == null || candidateId <= 0 || typeof window === "undefined") return null;
  return `${PREFIX}${userId}:${candidateId}`;
}

function expired(entry: { updatedAt?: unknown }, now: number): boolean {
  return typeof entry.updatedAt !== "number" || now - entry.updatedAt > SCREENING_MEMORY_TTL_MS;
}

/** Wpis z karty albo `null` (brak, zepsuty, wygasły — wygasły znika). */
export function readStoredScreeningMemory(
  userId: number | undefined,
  candidateId: number,
  now: number = Date.now(),
): { updatedAt: number } | null {
  const key = storageKey(userId, candidateId);
  if (!key) return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { updatedAt?: unknown } | null;
    if (!parsed || typeof parsed !== "object" || expired(parsed, now)) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return parsed as { updatedAt: number };
  } catch {
    return null;
  }
}

/** `null` usuwa wpis. */
export function writeStoredScreeningMemory(
  userId: number | undefined,
  candidateId: number,
  entry: { updatedAt: number } | null,
): void {
  const key = storageKey(userId, candidateId);
  if (!key) return;
  try {
    if (entry) window.sessionStorage.setItem(key, JSON.stringify(entry));
    else window.sessionStorage.removeItem(key);
  } catch {
    /* pamięć zablokowana albo pełna — formularz pamięta rozmowę do przeładowania */
  }
}

/** Wylogowanie i martwa sesja: odpowiedzi kandydata nie czekają na kolejną osobę. */
export function clearScreeningMemories(): void {
  if (typeof window === "undefined") return;
  try {
    for (let i = window.sessionStorage.length - 1; i >= 0; i -= 1) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(PREFIX)) window.sessionStorage.removeItem(key);
    }
  } catch {
    /* pamięć zablokowana — nie ma czego czyścić */
  }
}
