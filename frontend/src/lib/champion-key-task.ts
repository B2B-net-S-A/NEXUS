/**
 * „Najważniejsze zadanie w tej roli” (Artur, warsztaty 23.11.2026).
 *
 * Delivery Lead wpisuje w Profilu Championa jedno zadanie, które klient uważa
 * za najważniejsze, i zaznacza pytanie screeningowe, które je sprawdza.
 * Zadanie i odpowiedź kandydata na to pytanie są wkładem do zdania 3
 * „Dlaczego nasz kandydat” w nowym CV. Bramka przekazania: kod `key_task`.
 */

import type { ChampionProfile } from "@/lib/api";

export interface KeyTask {
  task: string;
  /** Indeks pytania screeningowego, które sprawdza zadanie; null = nie wskazano. */
  questionIndex: number | null;
}

/** Zadanie z profilu albo `null`, gdy DL go nie wpisał (profile sprzed 23.11.2026). */
export function keyTaskOf(profile: Partial<ChampionProfile>): KeyTask | null {
  const task = (profile.project?.key_task ?? "").trim();
  if (!task) return null;
  const index = (profile.screening_questions ?? []).findIndex((q) => q.key_task && q.question.trim());
  return { task, questionIndex: index >= 0 ? index : null };
}

/** Indeks pytania oznaczonego jako sprawdzające zadanie (także bez wpisanego zadania). */
export function keyTaskQuestionIndex(questions: ChampionProfile["screening_questions"]): number | null {
  const index = questions.findIndex((q) => q.key_task);
  return index >= 0 ? index : null;
}

/** Oznacz pytanie `index` jako sprawdzające zadanie; pozostałe tracą oznaczenie. */
export function flagKeyTaskQuestion(
  questions: ChampionProfile["screening_questions"],
  index: number,
): ChampionProfile["screening_questions"] {
  return questions.map((q, i) => ({ ...q, key_task: i === index }));
}
