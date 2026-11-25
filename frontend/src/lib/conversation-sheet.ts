/**
 * „Arkusz rozmowy” (rekomendacja 2 z analizy dnia rekrutera, decyzja Artura
 * 23.11.2026): w „Trybie rozmowy” formularz screeningu stoi w dużej lewej
 * połowie panelu. Tu tylko liczenie paska nad arkuszem i podział pól
 * „Warunków” — reguły braków są te same co w stopce formularza
 * (`minimumMissingForForward`, `assessmentMissingForForward`).
 */

import type { ScreeningQuestion } from "@/lib/api";
import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { CARD_TERMS_ORDER } from "@/lib/recommendation-card";
import {
  assessmentMissingForForward,
  formFieldLabel,
  minimumMissingForForward,
  type ScreeningFullFormValues,
} from "@/lib/screening-form";

export interface SheetGap {
  key: string;
  label: string;
}

export interface ConversationSheetProgress {
  /** Pola, bez których „Zapisz i przekaż dalej” się zatrzyma (kolejność stopki). */
  missing: SheetGap[];
  answered: number;
  questions: number;
  checksDone: number;
  checks: number;
}

type ProgressState = Pick<ScreeningFormState, "card" | "sheet" | "note_answers" | "questions">;
type ProgressValues = Pick<ScreeningFullFormValues, "card" | "answers" | "experience_checks">;

export function conversationSheetProgress(
  state: ProgressState,
  questions: readonly ScreeningQuestion[],
  values: ProgressValues,
): ConversationSheetProgress {
  const keys = minimumMissingForForward(state, questions, values);
  // Rekrutacja bez pytań: stopka pomija wtedy „Dlaczego ten kandydat” w minimum,
  // bo zatrzymuje je osobna reguła — na pasku to ten sam brak.
  if (assessmentMissingForForward(state, questions, values) && !keys.includes("recommendation")) {
    keys.push("recommendation");
  }
  const checks = values.experience_checks ?? [];
  return {
    missing: keys.map((key) => ({ key, label: formFieldLabel(state, key) })),
    answered: questions.filter((q) => (values.answers?.[q.id]?.response ?? "").trim() !== "").length,
    questions: questions.length,
    checksDone: checks.filter((row) => row.status !== "unknown").length,
    checks: checks.length,
  };
}

/** Pola „Warunków” rzadko wypełniane w rozmowie — w arkuszu pod „pokaż”. */
const RARE_TERMS: ReadonlySet<string> = new Set(["nationality"]);
const KNOWN_TERMS: ReadonlySet<string> = new Set(CARD_TERMS_ORDER);

/**
 * Dzieli pola „Warunków” na widoczne i schowane pod „pokaż”. Rzadkie to
 * narodowość i pola spoza wzoru działu (np. dołożone przez klienta), ale nigdy
 * pole, które trzeba wypełnić albo które już ma wartość (`keep`).
 */
export function splitSheetTerms(
  keys: readonly string[],
  keep: ReadonlySet<string>,
): { common: string[]; rare: string[] } {
  const common: string[] = [];
  const rare: string[] = [];
  for (const key of keys) {
    const isRare = RARE_TERMS.has(key) || !KNOWN_TERMS.has(key);
    (isRare && !keep.has(key) ? rare : common).push(key);
  }
  return { common, rare };
}
