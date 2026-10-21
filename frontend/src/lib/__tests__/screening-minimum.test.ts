/**
 * Minimum dla Delivery Leada przed „Zweryfikowany” i pola przeniesione
 * z innej rekrutacji osoby (decyzje Artura 21.10.2026) — czysta logika.
 */
import { describe, expect, it } from "vitest";

import type { ScreeningFormCard } from "@/lib/api/screeningForm";
import { verifiedRequirementsOf } from "@/lib/verified-gate";
import {
  cardValueCounts,
  carriedCaption,
  carriedPrefill,
  minimumMissingForForward,
} from "@/lib/screening-form";
import { FORM_QUESTIONS, formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const REQUIRED = ["location", "work_mode", "availability", "recommendation"];

function card(overrides: Partial<ScreeningFormCard> = {}): ScreeningFormCard {
  const base = formState().card!;
  return {
    ...base,
    editable_fields: ["availability", "work_mode", "location", "rate", "recommendation", "red_flags"],
    required: REQUIRED,
    ...overrides,
  };
}

describe("cardValueCounts — lustro has_value z backendu", () => {
  it("„-”, „.”, „?” i puste nie są wartością; red flags „-” jest", () => {
    expect(cardValueCounts("location", "-")).toBe(false);
    expect(cardValueCounts("location", " . ")).toBe(false);
    expect(cardValueCounts("work_mode", "?")).toBe(false);
    expect(cardValueCounts("location", "")).toBe(false);
    expect(cardValueCounts("location", "Łódź")).toBe(true);
    expect(cardValueCounts("english", "B2")).toBe(true);
    expect(cardValueCounts("red_flags", "-")).toBe(true);
    expect(cardValueCounts("red_flags", "  ")).toBe(false);
  });
});

describe("minimumMissingForForward", () => {
  it("wymienia brakujące pola minimum w kolejności serwera", () => {
    const state = formState({ card: card() });
    expect(minimumMissingForForward(state, FORM_QUESTIONS, { card: { location: "-", work_mode: "zdalnie" } })).toEqual([
      "location",
      "availability",
      "recommendation",
    ]);
    expect(
      minimumMissingForForward(state, FORM_QUESTIONS, {
        card: { location: "Kraków", work_mode: "zdalnie", availability: "od zaraz", recommendation: "6 lat w Javie." },
      }),
    ).toEqual([]);
  });

  it("dostępność z profilu, wartość z notatki przy pustym polu i rekrutacja bez pytań", () => {
    const state = formState({
      card: card({
        availability_in_profile: true,
        fields: { location: { raw: "Gdańsk", source: "note" } },
      }),
    });
    // Puste pole nie kasuje wartości z notatki; dostępność jest w profilu.
    expect(minimumMissingForForward(state, FORM_QUESTIONS, { card: { work_mode: "hybryda" } })).toEqual([
      "recommendation",
    ]);
    // Bez pytań i bez odpowiedzi „Dlaczego” zatrzymuje `assessmentMissingForForward` — raz.
    expect(minimumMissingForForward(state, [], { card: { work_mode: "hybryda" } })).toEqual([]);
    // Odpowiedzi z notatki spełniają rozmowę, ale nie zastępują „Dlaczego” (przegląd 21.10).
    const withNote = formState({
      card: state.card,
      note_answers: [{ question_id: "q1", number: 1, question: "Ile lat Java?", answer: "6" }],
    });
    expect(minimumMissingForForward(withNote, [], { card: { work_mode: "hybryda" } })).toEqual([
      "recommendation",
    ]);
  });

  it("bez listy `required` (wyłącznik, starszy serwer) niczego nie wymaga", () => {
    expect(minimumMissingForForward(formState(), FORM_QUESTIONS, { card: {} })).toEqual([]);
  });
});

describe("carriedPrefill — pola o osobie z innej rekrutacji (D2)", () => {
  const carried = {
    location: { raw: "Warszawa", at: "2026-10-20T10:00:00+00:00", job_id: 7, job_title: "Java Developer — Bank A" },
    work_mode: { raw: "-", at: "2026-10-20T10:00:00+00:00", job_id: 7 },
    nationality: { raw: "polska", at: "2026-10-20T10:00:00+00:00", job_id: 7 },
  };

  it("wpisuje tylko w puste, edytowalne pola w Nowych i Screeningu", () => {
    const state = formState({ board_column: "screening", card: card({ carried }) });
    // „-” nie przechodzi, narodowości nie ma w polach formularza.
    expect(Object.keys(carriedPrefill(state))).toEqual(["location"]);
    const filled = formState({
      board_column: "screening",
      card: card({ carried, fields: { location: { raw: "Kraków", source: "manual" } } }),
    });
    expect(carriedPrefill(filled)).toEqual({});
  });

  it("nie wpisuje w dalszych kolumnach ani bez prawa zapisu", () => {
    expect(carriedPrefill(formState({ board_column: "verified", card: card({ carried }) }))).toEqual({});
    expect(carriedPrefill(formState({ editable: false, card: card({ carried }) }))).toEqual({});
  });

  it("podpis mówi, z której rozmowy jest wartość", () => {
    expect(carriedCaption(carried.location)).toBe("z rozmowy 20.10.2026 · Java Developer — Bank A");
    expect(carriedCaption({ raw: "x", at: "", job_id: 1 })).toBe("z rozmowy");
  });
});

describe("verifiedRequirementsOf — pola karty z odmowy 409", () => {
  it("oddaje `cardFields`, a stare klucze filtruje jak dotąd", () => {
    const error = {
      response: {
        status: 409,
        data: {
          detail: {
            code: "VERIFIED_REQUIREMENTS_MISSING",
            missing: ["location", "work_mode"],
            card_fields: ["location", "work_mode"],
            screening_stage_id: 5,
            message: "Przed „Zweryfikowany” uzupełnij: „Lokalizacja”, „Tryb pracy”.",
          },
        },
      },
    };
    expect(verifiedRequirementsOf(error)).toEqual({
      missing: [],
      cardFields: ["location", "work_mode"],
      screeningStageId: 5,
      message: "Przed „Zweryfikowany” uzupełnij: „Lokalizacja”, „Tryb pracy”.",
    });
  });
});
