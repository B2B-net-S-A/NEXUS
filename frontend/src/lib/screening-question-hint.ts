/**
 * Podpowiedź przy pytaniu screeningowym w Profilu Championa (23.10.2026).
 *
 * Generator CV bierze z odpowiedzi tylko fakty o kandydacie. Pytanie tak/nie
 * daje samo „tak”, a pytanie o metodę („Jak analizujesz…?”) — odpowiedź
 * z teorii. Lepsze jest pytanie o to, co kandydat zrobił, gdzie i jak długo.
 * Podpowiedź nie blokuje zapisu.
 */

const YES_NO = /^\s*czy\s/iu;
const METHOD = /^\s*(?:jak|w\s+jaki\s+sposób)\s/iu;
// Pytanie o przeszłość albo doświadczenie daje fakty mimo „Jak…”
// („Jak weryfikowałeś…”, „Jak długo…”, „Jakie masz doświadczenie…”).
const ASKS_FOR_FACTS = /(?:łeś|łaś)(?!\p{L})|jak\s+długo|doświadcz|projekt|gdzie|kiedy/iu;

export function screeningQuestionHint(question: string | null | undefined): string | null {
  const text = (question ?? "").trim();
  if (!text) return null;
  if (YES_NO.test(text)) {
    return "Pytanie tak/nie daje samo „tak”, z którego nie powstanie CV. Lepiej: „Gdzie i jak długo…? Co tam robiłeś?”";
  }
  if (METHOD.test(text) && !ASKS_FOR_FACTS.test(text)) {
    return "Pytanie o metodę daje odpowiedź z teorii. Do CV lepiej: „W jakim projekcie…? Co tam konkretnie robiłeś?”";
  }
  return null;
}
