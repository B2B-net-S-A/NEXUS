/**
 * Formularz screeningu (0424) — czysta logika: wartości startowe, ładunek
 * zapisu (tylko zmiany), wypełnienie z notatki i walidacja „przekaż dalej”.
 */
import { describe, expect, it } from "vitest";

import type { NoteProposal } from "@/lib/api/recommendationCards";
import {
  AFTER_CV_SENT_COLUMNS,
  answerOriginAfterEdit,
  applyFillsToValues,
  applyNoteProposal,
  buildSavePayload,
  cardAssessmentKeys,
  cardOriginAfterEdit,
  cardTermsKeys,
  editableCardKeys,
  fillPatches,
  fillTarget,
  formDefaultsFromState,
  formFieldLabel,
  formatFormRate,
  hasSheetContent,
  mergeLegacyNote,
  missingAnswersForForward,
  parseRateAmount,
  rateFromValues,
  sameRate,
  versionActionLabel,
} from "@/lib/screening-form";
import { FORM_QUESTIONS, formState } from "@/test/fixtures/screening-form";

const SAVED_SHEET = {
  answers: [
    { question_id: "q1", response: "6 lat", deal_breaker_hit: false },
    { question_id: "q2", response: "", deal_breaker_hit: false },
  ],
  overall_fit: "fit" as const,
  notes: "",
};

function proposal(partial: Partial<Pick<NoteProposal, "fields" | "answers">>): Pick<NoteProposal, "fields" | "answers"> {
  return { fields: [], answers: [], ...partial };
}

describe("klucze pól karty", () => {
  it("stawka nie jest polem karty — ma własne pole formularza", () => {
    const state = formState();
    expect(editableCardKeys(state)).not.toContain("rate");
    expect(cardTermsKeys(state)).toEqual(["availability", "work_mode"]);
    expect(cardAssessmentKeys(state)).toEqual(["recommendation", "red_flags"]);
  });

  it("etykieta „recommendation” to „Dlaczego ten kandydat”, nie „Notatka”", () => {
    expect(formFieldLabel(formState(), "recommendation")).toBe("Dlaczego ten kandydat");
    expect(formFieldLabel(formState(), "availability")).toBe("Dostępność");
  });
});

describe("formDefaultsFromState", () => {
  it("bierze odpowiedzi arkusza, pola karty i stawkę; stara notatka nie trafia do pola", () => {
    const state = formState({
      sheet: SAVED_SHEET,
      legacy_notes: "Stara notatka z arkusza",
      card: {
        ...formState().card,
        fields: { availability: { raw: "od 1.11", source: "manual" } },
      },
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "stage", at: null },
    });
    const values = formDefaultsFromState(state);
    expect(values.answers.q1.response).toBe("6 lat");
    expect(values.answers.q2.response).toBe("");
    expect(values.overall_fit).toBe("fit");
    expect(values.notes).toBe("");
    expect(values.card).toEqual({ availability: "od 1.11", work_mode: "", recommendation: "", red_flags: "" });
    expect(values.rate_amount).toBe("150");
    expect(values.rate_unit).toBe("hourly");
  });

  it("hasSheetContent = choć jedna niepusta odpowiedź", () => {
    expect(hasSheetContent(formState())).toBe(false);
    expect(hasSheetContent(formState({ sheet: SAVED_SHEET }))).toBe(true);
    expect(
      hasSheetContent(
        formState({
          sheet: { answers: [{ question_id: "q1", response: "  ", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
        }),
      ),
    ).toBe(false);
  });
});

describe("buildSavePayload", () => {
  it("bez zmian — brak zapisu", () => {
    const state = formState({ sheet: SAVED_SHEET, version: 4 });
    const plan = buildSavePayload(state, formDefaultsFromState(state));
    expect(plan.hasChanges).toBe(false);
    expect(plan.payload).toMatchObject({ sheet: null, card: null, rate: null, note_import: null, expected_version: 4 });
  });

  it("zmiana odpowiedzi wysyła cały arkusz, karta i stawka zostają `null`", () => {
    const state = formState({ sheet: SAVED_SHEET, version: 2 });
    const values = formDefaultsFromState(state);
    values.answers.q2 = { ...values.answers.q2, response: "Tak, 2 lata" };
    const plan = buildSavePayload(state, values);
    expect(plan.hasChanges).toBe(true);
    expect(plan.payload.sheet?.answers).toEqual([
      { question_id: "q1", response: "6 lat", deal_breaker_hit: false, origin: "manual" },
      { question_id: "q2", response: "Tak, 2 lata", deal_breaker_hit: false, origin: "manual" },
    ]);
    expect(plan.payload.sheet?.overall_fit).toBe("fit");
    expect(plan.payload.card).toBeNull();
    expect(plan.payload.rate).toBeNull();
  });

  it("pola karty: tylko zmienione, z pochodzeniem z notatki", () => {
    const state = formState();
    const values = formDefaultsFromState(state);
    values.card.availability = "od zaraz";
    values.card_origins.availability = { origin: "note_ai" };
    values.card.red_flags = "Brak";
    const plan = buildSavePayload(state, values);
    expect(plan.payload.card).toEqual({
      fields: { availability: "od zaraz", red_flags: "Brak" },
      origins: { availability: { origin: "note_ai" } },
    });
    expect(plan.payload.sheet).toBeNull();
  });

  it("wyczyszczenie pola z notatki nie kasuje wartości z notatki; pole wpisane ręcznie — tak", () => {
    const state = formState({
      card: {
        ...formState().card,
        fields: {
          availability: { raw: "od 1.11", source: "note" },
          work_mode: { raw: "zdalnie", source: "manual" },
        },
      },
    });
    const values = formDefaultsFromState(state);
    values.card.availability = "";
    values.card.work_mode = "";
    const plan = buildSavePayload(state, values);
    expect(plan.payload.card).toEqual({ fields: { work_mode: null } });
  });

  it("„zdanie z haseł” w polu nieopisowym nie idzie jako pochodzenie", () => {
    const state = formState();
    const values = formDefaultsFromState(state);
    values.card.availability = "Od listopada";
    values.card_origins.availability = { origin: "phrased", keywords: "listopad" };
    values.card.recommendation = "Mocny backend";
    values.card_origins.recommendation = { origin: "phrased", keywords: "backend mocny" };
    const plan = buildSavePayload(state, values);
    expect(plan.payload.card?.origins).toEqual({
      recommendation: { origin: "phrased", keywords: "backend mocny" },
    });
  });

  it("stawka: tylko inna niż zapisana i tylko z prawem edycji", () => {
    const saved = { amount: 150, unit: "hourly" as const, currency: "PLN", source: "stage" as const, at: null };
    const state = formState({ rate: saved });
    const same = formDefaultsFromState(state);
    expect(buildSavePayload(state, { ...same, rate_amount: "150,00" }).payload.rate).toBeNull();
    expect(buildSavePayload(state, { ...same, rate_amount: "160" }).payload.rate).toEqual({
      amount: 160,
      unit: "hourly",
      currency: "PLN",
    });
    const noRight = formState({ rate: saved, can_edit_rate: false });
    expect(buildSavePayload(noRight, { ...same, rate_amount: "160" }).payload.rate).toBeNull();
  });

  it("notatka idzie razem z zapisem, także gdy pola są bez zmian", () => {
    const state = formState();
    const plan = buildSavePayload(state, formDefaultsFromState(state), {
      noteImport: { text: "Rozmowa: Java 6 lat", source_name: "notatka.docx" },
    });
    expect(plan.hasChanges).toBe(true);
    expect(plan.payload.note_import).toEqual({ text: "Rozmowa: Java 6 lat", source_name: "notatka.docx" });
  });

  it("„Przenieś do Dlaczego ten kandydat” czyści notatkę z arkusza", () => {
    const state = formState({ sheet: SAVED_SHEET, legacy_notes: "Stara notatka" });
    const values = formDefaultsFromState(state);
    values.card.recommendation = mergeLegacyNote("", "Stara notatka");
    values.clear_legacy_notes = true;
    const plan = buildSavePayload(state, values);
    expect(plan.payload.sheet?.clear_legacy_notes).toBe(true);
    expect(plan.payload.card?.fields).toEqual({ recommendation: "Stara notatka" });
  });

  it("pominięte przy przepięciu: odpowiedź `skipped` i domyślna notatka wewnętrzna", () => {
    const state = formState();
    const values = formDefaultsFromState(state);
    values.skip_missing = true;
    values.answers.q1 = { ...values.answers.q1, response: "5 lat" };
    const sheet = buildSavePayload(state, values).payload.sheet;
    expect(sheet?.answers[1]).toMatchObject({ question_id: "q2", skipped: true });
    expect(sheet?.internal_note).toBe("Pominięte — przepięcie");
  });

  it("odpowiedź przepisana przez automat zapisuje się jako odpowiedź z notatki z hasłami", () => {
    const state = formState();
    const values = formDefaultsFromState(state);
    values.answers.q1 = { response: "6 lat", deal_breaker_hit: false, origin: "note_sync", keywords: "java 6" };
    expect(buildSavePayload(state, values).payload.sheet?.answers[0]).toEqual({
      question_id: "q1",
      response: "6 lat",
      deal_breaker_hit: false,
      origin: "note_import",
      keywords: "java 6",
    });
  });
});

describe("stawka", () => {
  it("parseRateAmount: przecinek, puste, zero i ujemne", () => {
    expect(parseRateAmount("150,5")).toBe(150.5);
    expect(parseRateAmount("")).toBeNull();
    expect(parseRateAmount("0")).toBeNull();
    expect(parseRateAmount("-5")).toBeNull();
    expect(parseRateAmount("abc")).toBeNull();
  });

  it("rateFromValues + sameRate + formatFormRate", () => {
    const rate = rateFromValues({ rate_amount: "1200", rate_unit: "daily", rate_currency: "pln" });
    expect(rate).toEqual({ amount: 1200, unit: "daily", currency: "PLN" });
    expect(sameRate(rate, { amount: 1200.001, unit: "daily", currency: "PLN" })).toBe(true);
    expect(sameRate(rate, { amount: 1200, unit: "hourly", currency: "PLN" })).toBe(false);
    expect(sameRate(null, null)).toBe(true);
    expect(formatFormRate({ amount: 150, unit: "hourly", currency: "PLN" })).toBe("150 zł/h");
    expect(formatFormRate({ amount: 40, unit: "hourly", currency: "eur" })).toBe("40 EUR/h");
  });
});

describe("applyNoteProposal — notatka wypełnia puste, przy wpisanych proponuje", () => {
  const options = {
    editableCardKeys: ["availability", "work_mode", "recommendation"],
    canEditRate: true,
    questionIds: ["q1", "q2"],
  };

  it("puste pola karty i odpowiedzi wypełnia, wpisane — propozycja „Użyj”", () => {
    const values = formDefaultsFromState(formState());
    values.card.work_mode = "hybrydowo";
    values.answers.q2 = { ...values.answers.q2, response: "Nie" };
    const result = applyNoteProposal(
      values,
      proposal({
        fields: [
          { key: "availability", label: "Dostępność", current: null, current_source: null, proposed: "od zaraz", quote: "od zaraz", origin: "note_ai", changed: true },
          { key: "work_mode", label: "Tryb pracy", current: "hybrydowo", current_source: "manual", proposed: "zdalnie", quote: null, origin: "note_rule", changed: true },
          { key: "nationality", label: "Narodowość", current: null, current_source: null, proposed: "PL", quote: null, origin: "note_rule", changed: true },
        ],
        answers: [
          { question_id: "q1", number: 1, question: "Java?", current: null, keywords: "java 6 lat", sentence: "Pracuje z Javą od 6 lat.", problem: null },
          { question_id: "q2", number: 2, question: "Kafka?", current: "Nie", keywords: "kafka 2 lata", sentence: null, problem: null },
          { question_id: "qX", number: 3, question: "Spoza profilu", current: null, keywords: "x", sentence: null, problem: null },
        ],
      }),
      options,
    );
    expect(result.fills).toEqual([
      { kind: "card", key: "availability", value: "od zaraz", origin: "note_ai" },
      { kind: "answer", questionId: "q1", response: "Pracuje z Javą od 6 lat.", origin: "phrased", keywords: "java 6 lat" },
    ]);
    expect(result.offers.map((o) => o.id)).toEqual(["card:work_mode", "answer:q2"]);
    expect(result.offers[1]).toMatchObject({ response: "kafka 2 lata", origin: "note_import", label: "Pytanie 2" });
  });

  it("stawka: strukturalna wypełnia pole, tekstowa jest tylko podpowiedzią", () => {
    const values = formDefaultsFromState(formState());
    const structured = applyNoteProposal(
      values,
      proposal({
        fields: [
          { key: "rate", label: "Stawka", current: null, current_source: null, proposed: "150 zł/h", quote: null, origin: "note_rule", changed: true, rate: { amount: 150, unit: "hourly", currency: "PLN" } },
        ],
      }),
      options,
    );
    expect(structured.fills).toEqual([{ kind: "rate", rate: { amount: 150, unit: "hourly", currency: "PLN" } }]);

    const textual = applyNoteProposal(
      values,
      proposal({
        fields: [
          { key: "rate", label: "Stawka", current: null, current_source: null, proposed: "12 tys. na rękę", quote: null, origin: "note_ai", changed: true, rate: null },
        ],
      }),
      options,
    );
    expect(textual.fills).toEqual([]);
    expect(textual.hints).toEqual([{ id: "rate", label: "Stawka", text: "12 tys. na rękę" }]);

    const noRight = applyNoteProposal(
      values,
      proposal({
        fields: [
          { key: "rate", label: "Stawka", current: null, current_source: null, proposed: "150 zł/h", quote: null, origin: "note_rule", changed: true, rate: { amount: 150, unit: "hourly", currency: "PLN" } },
        ],
      }),
      { ...options, canEditRate: false },
    );
    expect(noRight.fills).toEqual([]);
  });

  it("inna stawka niż wpisana = propozycja; ta sama = nic", () => {
    const values = { ...formDefaultsFromState(formState()), rate_amount: "140" };
    const field = {
      key: "rate",
      label: "Stawka",
      current: null,
      current_source: null,
      proposed: "150 zł/h",
      quote: null,
      origin: "note_rule" as const,
      changed: true,
      rate: { amount: 150, unit: "hourly" as const, currency: "PLN" },
    };
    expect(applyNoteProposal(values, proposal({ fields: [field] }), options).offers).toMatchObject([
      { id: "rate", text: "150 zł/h" },
    ]);
    expect(
      applyNoteProposal({ ...values, rate_amount: "150" }, proposal({ fields: [field] }), options).offers,
    ).toEqual([]);
  });

  it("fillPatches / fillTarget / applyFillsToValues mówią to samo", () => {
    const fills = [
      { kind: "card" as const, key: "availability", value: "od zaraz", origin: "note_rule" as const },
      { kind: "answer" as const, questionId: "q1", response: "6 lat", origin: "note_import" as const, keywords: "" },
      { kind: "rate" as const, rate: { amount: 150, unit: "hourly" as const, currency: "PLN" } },
    ];
    expect(fills.map(fillTarget)).toEqual(["card:availability", "answer:q1", "rate"]);
    expect(fillPatches(fills[1])).toEqual([
      ["answers.q1.response", "6 lat"],
      ["answers.q1.origin", "note_import"],
      ["answers.q1.keywords", null],
    ]);
    const next = applyFillsToValues(formDefaultsFromState(formState()), fills);
    expect(next.card.availability).toBe("od zaraz");
    expect(next.card_origins.availability).toEqual({ origin: "note_rule" });
    expect(next.answers.q1).toMatchObject({ response: "6 lat", origin: "note_import", keywords: null });
    expect(next.rate_amount).toBe("150");
  });
});

describe("pochodzenie po ręcznej poprawce", () => {
  it("odpowiedź z notatki/podpowiedzi poprawiona ręcznie = ręczna", () => {
    expect(answerOriginAfterEdit("note_import", "zmienione")).toBe("manual");
    expect(answerOriginAfterEdit("reassign_suggested", "x")).toBe("manual");
    expect(answerOriginAfterEdit("phrased", "dalej zdanie")).toBeNull();
    expect(answerOriginAfterEdit("phrased", "")).toBe("manual");
    expect(answerOriginAfterEdit("manual", "x")).toBeNull();
  });

  it("pole karty: notatka traci pochodzenie od razu, zdanie z haseł dopiero po wyczyszczeniu", () => {
    expect(cardOriginAfterEdit({ origin: "note_ai" }, "x")).toBe("clear");
    expect(cardOriginAfterEdit({ origin: "phrased", keywords: "a" }, "zdanie")).toBe("keep");
    expect(cardOriginAfterEdit({ origin: "phrased", keywords: "a" }, "")).toBe("clear");
    expect(cardOriginAfterEdit(null, "x")).toBe("keep");
  });
});

describe("walidacja i drobiazgi", () => {
  it("„przekaż dalej” wymaga odpowiedzi na każde pytanie — chyba że pominięte przy przepięciu", () => {
    const questions = FORM_QUESTIONS;
    const values = formDefaultsFromState(formState({ sheet: SAVED_SHEET }));
    expect(missingAnswersForForward(questions, values)).toEqual(["q2"]);
    expect(missingAnswersForForward(questions, { ...values, skip_missing: true })).toEqual([]);
  });

  it("mergeLegacyNote dopisuje pod tekstem", () => {
    expect(mergeLegacyNote("", "  stara ")).toBe("stara");
    expect(mergeLegacyNote("Mocny kandydat", "stara")).toBe("Mocny kandydat\n\nstara");
  });

  it("etykiety wersji i kolumny po wysłaniu CV", () => {
    expect(versionActionLabel("restore", 3)).toBe("Przywrócono wersję 3");
    expect(versionActionLabel("undo")).toBe("Cofnięto zapis");
    expect(versionActionLabel("baseline")).toBe("Stan przed formularzem");
    expect(versionActionLabel("fix_requested")).toBe("Wróciło do poprawy");
    expect(AFTER_CV_SENT_COLUMNS.has("cv_sent")).toBe(true);
    expect(AFTER_CV_SENT_COLUMNS.has("cv_qc")).toBe(false);
  });
});
