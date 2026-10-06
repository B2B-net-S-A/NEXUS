/**
 * Karta z notatki (0421) — czyste reguły przeglądu propozycji.
 *
 * Serwer proponuje pola i odpowiedzi; tu tylko: co zaznaczyć na starcie,
 * jak policzyć zaznaczone i jak złożyć zapis. Nic nie trafia do karty bez
 * „Zastosuj zaznaczone”.
 */

import type {
  CardAnswerOrigin,
  NoteApplyInput,
  NoteProposal,
} from "@/lib/api/recommendationCards";

export interface NoteAnswerChoice {
  selected: boolean;
  /** Treść, która trafi do arkusza — zdanie albo hasła, do poprawienia. */
  response: string;
}

export interface NoteReviewState {
  fields: Record<string, boolean>;
  answers: Record<string, NoteAnswerChoice>;
}

/** Na starcie zaznaczone: pola, które coś zmieniają, i odpowiedzi na pytania bez odpowiedzi. */
export function initialReviewState(proposal: NoteProposal): NoteReviewState {
  return {
    fields: Object.fromEntries(
      proposal.fields.map((field) => [field.key, field.changed]),
    ),
    answers: Object.fromEntries(
      proposal.answers.map((answer) => [
        answer.question_id,
        {
          selected: !answer.current,
          response: answer.sentence ?? answer.keywords,
        },
      ]),
    ),
  };
}

export function selectedCount(state: NoteReviewState): number {
  const fields = Object.values(state.fields).filter(Boolean).length;
  const answers = Object.values(state.answers).filter(
    (choice) => choice.selected && choice.response.trim(),
  ).length;
  return fields + answers;
}

/** Odpowiedź równa zdaniu od Luny = „zdanie z haseł”; inaczej — „z notatki”. */
export function answerOrigin(
  response: string,
  sentence: string | null | undefined,
): CardAnswerOrigin {
  return sentence && response.trim() === sentence.trim()
    ? "phrased"
    : "note_import";
}

export function buildApplyInput(
  proposal: NoteProposal,
  state: NoteReviewState,
  sourceName: string | null,
): NoteApplyInput {
  const fields: Record<string, string> = {};
  const fieldOrigins: NoteApplyInput["field_origins"] = {};
  for (const field of proposal.fields) {
    if (!state.fields[field.key]) continue;
    fields[field.key] = field.proposed;
    fieldOrigins[field.key] = field.origin;
  }
  const answers: NoteApplyInput["answers"] = [];
  for (const answer of proposal.answers) {
    const choice = state.answers[answer.question_id];
    const response = choice?.response.trim() ?? "";
    if (!choice?.selected || !response) continue;
    answers.push({
      question_id: answer.question_id,
      response,
      keywords: answer.keywords,
      origin: answerOrigin(response, answer.sentence),
    });
  }
  return {
    text: proposal.text,
    source_name: sourceName,
    fields,
    field_origins: fieldOrigins,
    answers,
  };
}

/** Zaznaczona zmiana stawki, która otworzy sprawę „zmiana stawki” u DL. */
export function rateChangeWarning(
  proposal: NoteProposal,
  state: NoteReviewState,
): boolean {
  return (
    proposal.rate_change_notifies &&
    proposal.fields.some(
      (field) => field.key === "rate" && field.changed && state.fields.rate,
    )
  );
}
