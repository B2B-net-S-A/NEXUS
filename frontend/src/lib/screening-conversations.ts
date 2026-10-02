// Karta „Odpowiedzi z rozmów screeningowych” w profilu kandydata — czyste
// funkcje: szukanie w odpowiedziach i podpisy rozmów. Dane liczy serwer
// (`GET /api/candidates/{id}/screening-answers`).

import type { ScreeningConversation } from "@/lib/api/screeningAnswers";

const fold = (value: string): string => value.toLocaleLowerCase("pl");

/** Odpowiedź z numerem pytania w arkuszu — po filtrze numeracja zostaje. */
export type PositionedAnswer = ScreeningConversation["answers"][number] & { position?: number };
export type FilteredConversation = Omit<ScreeningConversation, "answers"> & { answers: PositionedAnswer[] };

/**
 * Rozmowy pasujące do frazy, z samymi pasującymi odpowiedziami (każda niesie
 * swój numer pytania z arkusza). Fraza trafia w pytanie, odpowiedź, pozycję
 * „sprawdzone w rozmowie” albo notatkę. Pusta fraza = wszystko bez zmian.
 */
export function filterConversations(
  conversations: readonly ScreeningConversation[],
  phrase: string,
): FilteredConversation[] {
  const needle = fold(phrase.trim());
  if (!needle) return [...conversations];
  const hit = (text: string | null | undefined) => Boolean(text) && fold(text as string).includes(needle);
  const out: FilteredConversation[] = [];
  for (const conversation of conversations) {
    const answers = conversation.answers
      .map((answer, index) => ({ ...answer, position: index + 1 }))
      .filter((a) => hit(a.question_text) || hit(a.response));
    const checks = conversation.experience_checks.filter((c) => hit(c.name) || hit(c.note));
    const notes = hit(conversation.notes) ? conversation.notes : "";
    const internal = hit(conversation.internal_note) ? conversation.internal_note : null;
    if (answers.length === 0 && checks.length === 0 && !notes && !internal) continue;
    out.push({ ...conversation, answers, experience_checks: checks, notes, internal_note: internal });
  }
  return out;
}

/** „Senior Java Developer · Bank Przykładowy” — rekrutacja i klient rozmowy. */
export function conversationTitle(conversation: ScreeningConversation): string {
  const job = conversation.job_title?.trim() || `Rekrutacja #${conversation.job_id}`;
  const client = conversation.client_name?.trim();
  return client ? `${job} · ${client}` : job;
}

export const SCREENING_FIT_LABEL = { fit: "Pasuje", uncertain: "Niepewne", miss: "Nie pasuje" } as const;
export const SCREENING_FIT_VARIANT = { fit: "success", uncertain: "warning", miss: "danger" } as const;
