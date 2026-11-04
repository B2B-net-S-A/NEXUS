/**
 * Podpowiedź pod odpowiedzią ze screeningu (23.10.2026).
 *
 * Generator CV bierze z odpowiedzi tylko fakty o kandydacie. Zaślepka („x”,
 * „-”) nie trafia do CV wcale, a samo „tak” potwierdza tylko treść pytania —
 * bez firmy, projektu i czasu nie ma z czego napisać doświadczenia.
 * Ostrzeżenie nie blokuje zapisu.
 */

export const SCREENING_ANSWER_PLACEHOLDER =
  "Fakty do CV: co robił, gdzie (firma, projekt), jak długo. Np. „3 lata w projekcie dla banku: rozdzielił ruch Data i Management na osobne VLAN-y”.";

const PLACEHOLDER = /^[\W_]*(?:x+|n\/?a|b\/?d)?[\W_]*$/iu;
const BARE_YES = new Set(["tak", "yes", "owszem", "ok", "zna", "ma", "jest", "oczywiście", "potwierdza"]);

export function screeningAnswerHint(response: string | null | undefined): string | null {
  const text = (response ?? "").trim();
  if (!text) return null;
  if (PLACEHOLDER.test(text)) {
    return "To nie jest odpowiedź i nie trafi do CV. Wpisz, co powiedział kandydat, albo zostaw puste.";
  }
  const words = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  if (words.length > 0 && words.length <= 3 && words.every((word) => BARE_YES.has(word))) {
    return "Samo „tak” potwierdza tylko pytanie. Dopisz konkret: co robił, gdzie (firma, projekt), jak długo — z tego powstaje CV.";
  }
  return null;
}
