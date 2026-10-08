// Czyste reguły podpowiedzi przy „@” w notatkach i czatach (MentionTextarea).

export interface MentionCandidate {
  id: number;
  name: string;
  email: string;
  role: string;
}

export interface MentionToken {
  /** Pozycja znaku „@” w tekście. */
  start: number;
  /** Tekst wpisany po „@” (bez zmiany wielkości liter). */
  query: string;
}

const MAX_QUERY_LENGTH = 40;
const MAX_QUERY_WORDS = 3;

/** Bez polskich znaków i wielkości liter — „lukasz” znajduje „Łukasz”. */
export function foldMentionText(text: string): string {
  return text
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/\p{M}+/gu, "");
}

/**
 * „@…” tuż przed kursorem, które zaczyna wzmiankę. „@” w środku słowa nim nie
 * jest — to adres e-mail (także ten wstawiony przez wcześniejszą wzmiankę).
 * Po „@” wolno wpisać imię i nazwisko ze spacją.
 */
export function findMentionToken(text: string, caret: number): MentionToken | null {
  const before = text.slice(0, caret);
  const start = before.lastIndexOf("@");
  if (start === -1) return null;
  if (start > 0 && !/[\s([{„"]/.test(before[start - 1])) return null;
  const query = before.slice(start + 1);
  if (query.length > MAX_QUERY_LENGTH) return null;
  if (/^\s/.test(query) || /\n/.test(query) || /\s{2,}/.test(query)) return null;
  if (query.split(" ").length > MAX_QUERY_WORDS) return null;
  return { start, query };
}

function rank(user: MentionCandidate, query: string): number | null {
  const name = foldMentionText(user.name ?? "");
  // Sama część przed „@”: domena jest wspólna dla całej firmy, więc każda
  // jej litera pasowałaby do wszystkich.
  const email = foldMentionText(user.email.split("@")[0]);
  if (name.startsWith(query)) return 0;
  if (name.split(/\s+/).some((word) => word.startsWith(query))) return 1;
  // Imię i nazwisko ze spacją dopasowujemy tylko do nazwy — adres nie ma spacji.
  if (query.includes(" ")) return name.includes(query) ? 2 : null;
  if (email.startsWith(query)) return 2;
  if (name.includes(query) || email.includes(query)) return 3;
  return null;
}

/**
 * Osoby pasujące do wpisanego tekstu. Pusty tekst (samo „@”) = początek listy
 * w kolejności z serwera (zespół rekrutacji stoi tam pierwszy).
 */
export function matchMentionUsers<T extends MentionCandidate>(
  users: readonly T[],
  query: string,
  limit: number,
): T[] {
  const folded = foldMentionText(query);
  if (!folded) return users.slice(0, limit);
  return users
    .map((user, index) => ({ user, index, rank: rank(user, folded) }))
    .filter((row): row is { user: T; index: number; rank: number } => row.rank !== null)
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .slice(0, limit)
    .map((row) => row.user);
}

export interface PopupPlacement {
  side: "above" | "below";
  maxHeight: number;
}

const MIN_POPUP_HEIGHT = 120;
const POPUP_GAP = 8;

/**
 * Po której stronie pola otworzyć listę. Do 08.10.2026 zawsze nad polem —
 * w notatce profilu pole stoi przy górnej krawędzi karty i lista była ucięta.
 */
export function choosePopupPlacement(
  spaceAbove: number,
  spaceBelow: number,
  desired: number,
): PopupPlacement {
  const needed = desired + POPUP_GAP;
  const side =
    spaceBelow >= needed || spaceBelow >= spaceAbove ? "below" : "above";
  const space = side === "below" ? spaceBelow : spaceAbove;
  return {
    side,
    maxHeight: Math.max(MIN_POPUP_HEIGHT, Math.min(desired, space - POPUP_GAP)),
  };
}
