/**
 * „Arkusz rozmowy” (23.11.2026): pasek braków liczy to samo co stopka
 * „Minimum dla Delivery Leada”, a rzadkie pola „Warunków” chowają się tylko,
 * gdy nie są potrzebne.
 */
import { describe, expect, it } from "vitest";

import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import { conversationSheetProgress, splitSheetTerms } from "@/lib/conversation-sheet";
import { formQuestions, minimumMissingForForward } from "@/lib/screening-form";

function minimumState(required: string[], extra: Record<string, unknown> = {}) {
  const base = formState().card!;
  return formState({
    card: {
      ...base,
      labels: { ...base.labels, location: "Lokalizacja" },
      editable_fields: [...base.editable_fields, "location"],
      required,
      ...extra,
    },
  });
}

describe("conversationSheetProgress", () => {
  it("braki to braki stopki, w jej kolejności i z jej etykietami", () => {
    const state = minimumState(["location", "work_mode", "availability", "recommendation"]);
    const questions = formQuestions(state);
    const values = { card: { location: "", work_mode: "", availability: "", recommendation: "" }, answers: {}, experience_checks: [] };
    const progress = conversationSheetProgress(state, questions, values);
    expect(progress.missing.map((gap) => gap.key)).toEqual(minimumMissingForForward(state, questions, values));
    expect(progress.missing.map((gap) => gap.label)).toEqual(["Lokalizacja", "Tryb pracy", "Dostępność", "Dlaczego ten kandydat"]);
  });

  it("brak znika, gdy pole dostaje treść; samo „-” się nie liczy", () => {
    const state = minimumState(["location", "work_mode"]);
    const questions = formQuestions(state);
    const progress = conversationSheetProgress(state, questions, {
      card: { location: "-", work_mode: "hybrydowo" },
      answers: {},
      experience_checks: [],
    });
    expect(progress.missing.map((gap) => gap.key)).toEqual(["location"]);
  });

  it("liczy pytania z odpowiedzią i rozstrzygnięte „Sprawdź w rozmowie”", () => {
    const state = minimumState([]);
    const progress = conversationSheetProgress(state, formQuestions(state), {
      card: {},
      answers: {
        q1: { response: "6 lat", deal_breaker_hit: false },
        q2: { response: "   ", deal_breaker_hit: false },
      } as never,
      experience_checks: [
        { kind: "domains", name: "Bankowość", label: "Bankowość", level: "must", status: "confirmed" },
        { kind: "skills", name: "WCAG", label: "WCAG", level: "must", status: "unknown" },
        { kind: "skills", name: "Figma", label: "Figma", level: "nice", status: "not_confirmed" },
      ],
    });
    expect(progress).toMatchObject({ answered: 1, questions: 2, checksDone: 2, checks: 3, missing: [] });
  });

  it("rekrutacja bez pytań: pusty „Dlaczego ten kandydat” jest brakiem, choć stopka liczy go osobno", () => {
    const state = formState({ champion_profile: { screening_questions: [] } });
    const progress = conversationSheetProgress(state, [], { card: { recommendation: "" }, answers: {}, experience_checks: [] });
    expect(progress.missing).toEqual([{ key: "recommendation", label: "Dlaczego ten kandydat" }]);
  });
});

describe("splitSheetTerms", () => {
  it("narodowość i pola spoza wzoru działu idą pod „pokaż”", () => {
    expect(splitSheetTerms(["availability", "nationality", "location", "client_extra"], new Set())).toEqual({
      common: ["availability", "location"],
      rare: ["nationality", "client_extra"],
    });
  });

  // 25.11.2026: rekruterzy dopisywali managera w „Czy pracował u Klienta”
  // (179 kart na kopii produkcji), bo pole schowało się pod „pokaż”.
  it("„Manager u Klienta” stoi na wierzchu, nawet pusty", () => {
    expect(splitSheetTerms(["worked_at_client", "client_manager", "nationality"], new Set())).toEqual({
      common: ["worked_at_client", "client_manager"],
      rare: ["nationality"],
    });
  });

  it("pole wymagane albo z wartością zostaje na wierzchu", () => {
    expect(splitSheetTerms(["nationality", "client_extra"], new Set(["client_extra"]))).toEqual({
      common: ["client_extra"],
      rare: ["nationality"],
    });
  });
});
