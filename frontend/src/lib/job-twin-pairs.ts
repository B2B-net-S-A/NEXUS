/**
 * Pary pytań bliźniaków w oknie „Połącz bliźniaka” (0614, 28.10.2026).
 *
 * Każde pytanie tej rekrutacji ma najwyżej jedną parę w bliźniaku i odwrotnie
 * (ta sama reguła co serwer, `job_twins.validate_question_pairs`). Para mówi,
 * że w rozmowie zadajemy je raz, a odpowiedź trafia do arkusza obu rekrutacji.
 */

import type { QuestionPair } from "@/lib/job-twins-api";

/** Ustaw parę pytania tej rekrutacji; `null` = „tylko w tej rekrutacji”. */
export function setPair(pairs: readonly QuestionPair[], own: string, other: string | null): QuestionPair[] {
  const rest = pairs.filter((p) => p.own !== own && (other == null || p.other !== other));
  return other == null ? rest : [...rest, { own, other }];
}

export function pairOf(pairs: readonly QuestionPair[], own: string): string | null {
  return pairs.find((p) => p.own === own)?.other ?? null;
}

/** Pytania bliźniaka bez pary — zostają w sekcji „Tylko <bliźniak>”. */
export function unpairedOther(pairs: readonly QuestionPair[], otherIds: readonly string[]): string[] {
  const used = new Set(pairs.map((p) => p.other));
  return otherIds.filter((id) => !used.has(id));
}

/** Ile pytań padnie w rozmowie: wszystkie minus te, które łączy para. */
export function questionsInConversation(ownCount: number, otherCount: number, pairs: readonly QuestionPair[]): number {
  return ownCount + otherCount - pairs.length;
}
