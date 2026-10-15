/**
 * Szkic listy poprawek „Co poprawić?” z karty „CV do klienta” — per osoba
 * pisząca i wiersz etapu (15.10.2026). Lista ma do 2000 znaków, więc nie
 * może zniknąć przy przejściu do innej osoby ani po „Anuluj” w panelu.
 *
 * `sessionStorage`, świadomie NIE `localStorage` — ten sam powód co szkic
 * notatki (lib/note-drafts.ts): treść o kandydacie żyje najwyżej tyle co
 * karta przeglądarki, a wylogowanie kasuje ją wprost (`clearSessionArtifacts`
 * w lib/session.ts woła `clearCvRewriteDrafts`).
 *
 * Moduł bez importów (lib/session.ts go importuje). Pamięć przeglądarki bywa
 * zablokowana: wtedy pole działa bez szkicu, funkcje nigdy nie rzucają.
 */

const PREFIX = "nexus:cv-rewrite-draft:v1:";

function draftKey(userId: number | undefined, stageId: number): string | null {
  if (userId == null || typeof window === "undefined") return null;
  return `${PREFIX}${userId}:${stageId}`;
}

export function readCvRewriteDraft(userId: number | undefined, stageId: number): string {
  const key = draftKey(userId, stageId);
  if (!key) return "";
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

/** Pusty tekst (także same odstępy) usuwa szkic. */
export function writeCvRewriteDraft(userId: number | undefined, stageId: number, text: string): void {
  const key = draftKey(userId, stageId);
  if (!key) return;
  try {
    if (text.trim()) window.sessionStorage.setItem(key, text);
    else window.sessionStorage.removeItem(key);
  } catch {
    /* pamięć zablokowana albo pełna — pole działa bez szkicu */
  }
}

/** Wylogowanie i martwa sesja: szkice nie czekają na kolejną osobę przy tym komputerze. */
export function clearCvRewriteDrafts(): void {
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
