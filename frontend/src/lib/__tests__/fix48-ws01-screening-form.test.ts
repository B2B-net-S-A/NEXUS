/**
 * Audyt 48 h (13.10.2026), pkt 5: arkusz bez żadnej odpowiedzi (puste pola
 * każdego pytania, samo sprawdzenie doświadczenia) nie spełnia już bramki
 * „Zweryfikowany” na serwerze (`move_requirements.sheet_answered`). Formularz
 * w rekrutacji bez pytań liczy arkusz sprzed usunięcia pytań tak samo.
 */
import { describe, expect, it } from "vitest";

import type { ScreeningAnswerItem } from "@/lib/api";
import { assessmentMissingForForward } from "@/lib/screening-form";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const EMPTY_ANSWERS = {
  answers: [
    { question_id: "q1", response: "", deal_breaker_hit: false },
    { question_id: "q2", response: "   ", deal_breaker_hit: false },
  ],
  experience_checks: [{ kind: "domains" as const, name: "Bankowość", status: "confirmed" as const }],
  overall_fit: "fit" as const,
  notes: "",
};

describe("rekrutacja bez pytań: arkusz sprzed usunięcia pytań", () => {
  it("arkusz bez odpowiedzi nie zastępuje „Dlaczego ten kandydat”", () => {
    const state = formState({ champion_profile: {}, sheet: EMPTY_ANSWERS });
    expect(assessmentMissingForForward(state, [], { card: {} })).toBe(true);
  });

  it("odpowiedź z treścią, pominięcie albo deal-breaker wystarczą — jak na serwerze", () => {
    const answered = (answer: Partial<ScreeningAnswerItem>) =>
      formState({
        champion_profile: {},
        sheet: { ...EMPTY_ANSWERS, answers: [{ question_id: "q1", response: "", deal_breaker_hit: false, ...answer }] },
      });
    expect(assessmentMissingForForward(answered({ response: "5 lat" }), [], { card: {} })).toBe(false);
    expect(assessmentMissingForForward(answered({ skipped: true }), [], { card: {} })).toBe(false);
    expect(assessmentMissingForForward(answered({ deal_breaker_hit: true }), [], { card: {} })).toBe(false);
  });
});
