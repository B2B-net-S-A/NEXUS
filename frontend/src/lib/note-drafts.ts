/**
 * Szkic niewysłanej notatki z panelu osoby na Tablicy — per osoba pisząca,
 * rekrutacja i kandydat (12.10.2026). Do tej daty tekst znikał przy przejściu
 * do innej osoby.
 *
 * `sessionStorage`, świadomie NIE `localStorage`: notatka niesie dane
 * kandydata, więc żyje najwyżej tyle co karta przeglądarki, a wylogowanie
 * i martwa sesja kasują ją wprost (`clearSessionArtifacts` w lib/session.ts
 * woła `clearNoteDrafts`) — ten sam powód co w lib/talent-radar-session.ts.
 *
 * Moduł bez importów: lib/session.ts importuje go, a sam jest importowany
 * przez lib/api.ts i store/auth.ts — identyfikator osoby przychodzi
 * parametrem. Pamięć przeglądarki bywa zablokowana (tryb prywatny, polityka
 * firmy): wtedy pole działa bez szkicu, funkcje nigdy nie rzucają.
 */

const PREFIX = "nexus:note-draft:v1:";

function draftKey(userId: number | undefined, jobId: number, candidateId: number): string | null {
  if (userId == null || typeof window === "undefined") return null;
  return `${PREFIX}${userId}:${jobId}:${candidateId}`;
}

export function readNoteDraft(userId: number | undefined, jobId: number, candidateId: number): string {
  const key = draftKey(userId, jobId, candidateId);
  if (!key) return "";
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

/** Pusty tekst (także same odstępy) usuwa szkic. */
export function writeNoteDraft(
  userId: number | undefined,
  jobId: number,
  candidateId: number,
  text: string,
): void {
  const key = draftKey(userId, jobId, candidateId);
  if (!key) return;
  try {
    if (text.trim()) window.sessionStorage.setItem(key, text);
    else window.sessionStorage.removeItem(key);
  } catch {
    /* pamięć zablokowana albo pełna — pole działa bez szkicu */
  }
}

/** Wylogowanie i martwa sesja: szkice nie czekają na kolejną osobę przy tym komputerze. */
export function clearNoteDrafts(): void {
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
