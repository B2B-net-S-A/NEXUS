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
  assessmentMissingForForward,
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
  rateNotRestoredMessage,
  lowerKnownRate,
  lowerKnownRateText,
  ratePrefill,
  ratePrefillCaption,
  sameRate,
  sheetFromValues,
  versionActionLabel,
} from "@/lib/screening-form";
import { FORM_QUESTIONS, formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

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
  it("odsyła odcisk stanu, z którego wzięte są wartości", () => {
    const state = formState({ sheet: SAVED_SHEET, version: 4, state_token: "abc" });
    expect(buildSavePayload(state, formDefaultsFromState(state)).payload.state_token).toBe("abc");
    expect(
      buildSavePayload(state, formDefaultsFromState(state), { stateToken: "inny" }).payload.state_token,
    ).toBe("inny");
  });

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

  it("stawka z karty (etap bez stawki) idzie z zapisem — serwer porównuje tylko ze stawką etapu (14.10.2026)", () => {
    // Do 14.10.2026 formularz porównywał pole ze stawką z karty i nic nie
    // wysyłał, więc etap zostawał bez stawki, a „Zweryfikowany” jej żądał.
    const state = formState({ rate: { amount: 150, unit: "hourly", currency: "PLN", source: "card", at: null } });
    const plan = buildSavePayload(state, formDefaultsFromState(state));
    expect(plan.payload.rate).toEqual({ amount: 150, unit: "hourly", currency: "PLN" });
    expect(plan.hasChanges).toBe(true);
  });

  it("po „Zweryfikowany” stawka z karty nie idzie z zapisem sama — to podpowiedź, nie zmiana stawki (przegląd 14.10.2026)", () => {
    // Formularz jest edytowalny na każdym etapie; para z Traffita na „CV
    // wysłane” bez stawki etapu dostałaby przy zapisie odpowiedzi zmianę
    // stawki z dzwonkami do DL i rekrutera.
    const card = { amount: 150, unit: "hourly" as const, currency: "PLN", source: "card" as const, at: null };
    for (const board_column of ["verified", "cv_sent", "client_interview"]) {
      const state = formState({ board_column, rate: card });
      expect(buildSavePayload(state, formDefaultsFromState(state)).payload.rate).toBeNull();
      // Rekruter świadomie zmienia stawkę — wtedy idzie.
      expect(buildSavePayload(state, { ...formDefaultsFromState(state), rate_amount: "160" }).payload.rate).toEqual({
        amount: 160,
        unit: "hourly",
        currency: "PLN",
      });
    }
  });

  it("notatka zapisana w doku idzie z numerem — serwer jej nie dubluje (D3)", () => {
    const state = formState();
    const plan = buildSavePayload(state, formDefaultsFromState(state), {
      noteImport: { text: "Rozmowa: Java 6 lat", source_name: null, note_id: 55 },
    });
    expect(plan.payload.note_import).toEqual({ text: "Rozmowa: Java 6 lat", note_id: 55 });
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

describe("ratePrefill — stawka na start, gdy etap jej nie ma (D2, 14.10.2026)", () => {
  const NOTE_RATE = {
    value: 160,
    unit: "hour" as const,
    currency: "PLN",
    raw: "160 na B2B",
    source_note_id: null,
    noted_at: "2025-04-02",
  };
  const CARD = { amount: 150, unit: "hourly" as const, currency: "PLN" };
  const FROM = { amount: 140, unit: "hourly" as const, currency: "PLN" };

  it("R1 (17.10.2026): karta tej rekrutacji, potem niższa z notatki i „Stawki od”", () => {
    const all = formState({
      suggestions_from_notes: { rate: NOTE_RATE },
      rate_hints: { card: CARD, card_raw: "150 zł/h", rate_from: FROM },
    });
    expect(ratePrefill(all)).toEqual({ rate: CARD, origin: { kind: "card", quote: "150 zł/h" } });
    // Notatka 160 > „Stawka od” 140 — wpisuje się niższa.
    const noteHigher = formState({ suggestions_from_notes: { rate: NOTE_RATE }, rate_hints: { card: null, rate_from: FROM } });
    expect(ratePrefill(noteHigher)).toEqual({ rate: FROM, origin: { kind: "rate_from" } });
    // Notatka 90 < 140 — wpisuje się notatka z cytatem.
    const noteLower = formState({
      suggestions_from_notes: { rate: { ...NOTE_RATE, value: 90, raw: "Stawka: 90" } },
      rate_hints: { card: null, rate_from: FROM },
    });
    expect(ratePrefill(noteLower)).toEqual({
      rate: { amount: 90, unit: "hourly", currency: "PLN" },
      origin: { kind: "note", quote: "Stawka: 90", notedAt: "2025-04-02" },
    });
    const fromOnly = formState({ rate_hints: { card: null, rate_from: FROM } });
    expect(ratePrefill(fromOnly)).toEqual({ rate: FROM, origin: { kind: "rate_from" } });
    expect(ratePrefill(formState())).toBeNull();
  });

  it("notatka i „Stawka od” porównują się po godzinie; remis — notatka z cytatem", () => {
    const daily = { ...NOTE_RATE, value: 1200, unit: "day" as const, raw: "1200/MD" };
    expect(
      ratePrefill(formState({ suggestions_from_notes: { rate: daily }, rate_hints: { card: null, rate_from: FROM } }))?.origin.kind,
    ).toBe("rate_from");
    const tie = { ...NOTE_RATE, value: 140, raw: "140" };
    expect(
      ratePrefill(formState({ suggestions_from_notes: { rate: tie }, rate_hints: { card: null, rate_from: FROM } }))?.origin.kind,
    ).toBe("note");
  });

  it("żywa umowa: wpisuje się „Stawka u nas”, nie niższa notatka; karta tej rekrutacji dalej wygrywa", () => {
    const hints = { card: null, rate_from: { ...FROM, amount: 150 }, rate_from_source: "contract" };
    const lowNote = { ...NOTE_RATE, value: 90, raw: "Stawka: 90" };
    expect(ratePrefill(formState({ suggestions_from_notes: { rate: lowNote }, rate_hints: hints }))).toEqual({
      rate: { ...FROM, amount: 150 },
      origin: { kind: "contract" },
    });
    expect(ratePrefill(formState({ rate_hints: { ...hints, card: CARD, card_raw: "150 zł/h" } }))?.origin.kind).toBe("card");
  });

  it("notatka bez cytatu, w innej walucie albo bez jednostki nie wpisuje się — idzie następne źródło", () => {
    const hints = { card: null, rate_from: FROM };
    for (const rate of [
      { ...NOTE_RATE, raw: null },
      { ...NOTE_RATE, raw: "  " },
      { ...NOTE_RATE, currency: "EUR" },
      { ...NOTE_RATE, unit: null },
    ]) {
      expect(ratePrefill(formState({ suggestions_from_notes: { rate }, rate_hints: hints }))?.origin).toEqual({
        kind: "rate_from",
      });
    }
  });

  it("etap ze stawką albo brak prawa do stawek = nic", () => {
    const hints = { card: CARD, rate_from: FROM };
    expect(
      ratePrefill(
        formState({ rate: { ...CARD, source: "stage", at: null }, rate_hints: hints, suggestions_from_notes: { rate: NOTE_RATE } }),
      ),
    ).toBeNull();
    expect(ratePrefill(formState({ can_edit_rate: false, rate_hints: hints }))).toBeNull();
    // Tylko „Nowi” i „Screening” — dalej podpowiedź nie staje się stawką sama.
    expect(ratePrefill(formState({ board_column: "cv_sent", rate_hints: hints }))).toBeNull();
    expect(ratePrefill(formState({ board_column: "screening", rate_hints: hints }))).not.toBeNull();
  });

  it("stawka z karty w polu (etap bez stawki) zostaje — notatka jej nie zastępuje (R1)", () => {
    const state = formState({
      rate: { ...CARD, source: "card", at: null },
      rate_hints: { card: CARD, rate_from: null },
      suggestions_from_notes: { rate: { ...NOTE_RATE, value: 90 } },
    });
    expect(ratePrefill(state)?.origin.kind).toBe("card");
  });

  it("podpis pod polem mówi, skąd jest stawka", () => {
    expect(ratePrefillCaption({ kind: "note", quote: "160 na B2B", notedAt: "2025-04-02" })).toBe(
      "z notatki 2.04.2025: „160 na B2B”",
    );
    expect(ratePrefillCaption({ kind: "note", quote: "160", notedAt: "2025-04" })).toBe("z notatki 04.2025: „160”");
    expect(ratePrefillCaption({ kind: "note", quote: "160", notedAt: null })).toBe("z notatki: „160”");
    expect(ratePrefillCaption({ kind: "card", quote: "150 zł/h" })).toBe("z karty rekomendacji: „150 zł/h”");
    expect(ratePrefillCaption({ kind: "card", quote: null })).toBe("z karty rekomendacji");
    expect(ratePrefillCaption({ kind: "rate_from" })).toBe("Stawka od · najniższa z 18 mies.");
    expect(ratePrefillCaption({ kind: "contract" })).toBe("Stawka u nas · z umowy");
  });
});

describe("lowerKnownRate — niższa znana stawka w ostrzeżeniu „ponad budżet” (R2, 17.10.2026)", () => {
  const FROM = { amount: 90, unit: "hourly" as const, currency: "PLN" };
  const ENTERED = { amount: 140, unit: "hourly" as const, currency: "PLN" };

  it("ponad budżet i niższa stawka w budżecie — pokazuje najniższą z datą", () => {
    const state = formState({ rate_hints: { card: null, rate_from: FROM, rate_from_at: "2026-10-08T14:30:45Z" } });
    expect(lowerKnownRate(state, ENTERED, 135)).toEqual({
      rate: FROM,
      source: "rate_from",
      at: "2026-10-08T14:30:45Z",
    });
    expect(lowerKnownRateText({ rate: FROM, source: "rate_from", at: "2026-10-08T14:30:45Z" })).toBe(
      "Znana też niższa stawka: 90 zł/h (Stawka od, 8.10.2026) — mieści się w budżecie.",
    );
  });

  it("w budżecie, bez budżetu albo bez niższej stawki w budżecie — nic", () => {
    const state = formState({ rate_hints: { card: null, rate_from: FROM } });
    expect(lowerKnownRate(state, { ...ENTERED, amount: 130 }, 135)).toBeNull();
    expect(lowerKnownRate(state, ENTERED, null)).toBeNull();
    const high = formState({ rate_hints: { card: null, rate_from: { ...FROM, amount: 138 } } });
    expect(lowerKnownRate(high, ENTERED, 135)).toBeNull();
  });

  it("przy umowie liczy się deklaracja, nie „Stawka u nas”; notatka też", () => {
    const contract = formState({
      rate_hints: {
        card: null,
        rate_from: { ...FROM, amount: 150 },
        rate_from_source: "contract",
        declared_from: { ...FROM, amount: 120 },
        declared_from_at: "2026-09-01T10:00:00Z",
      },
    });
    expect(lowerKnownRate(contract, { ...ENTERED, amount: 150 }, 135)?.source).toBe("declared");
    const note = formState({
      rate_hints: { card: null, rate_from: null },
      suggestions_from_notes: {
        rate: { value: 100, unit: "hour", currency: "PLN", raw: "100", source_note_id: null, noted_at: null },
      },
    });
    expect(lowerKnownRate(note, ENTERED, 135)?.source).toBe("note");
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

  it("rekrutacja bez pytań: „przekaż dalej” wymaga „Dlaczego ten kandydat” (12.10.2026)", () => {
    const state = formState({ champion_profile: {} });
    const values = formDefaultsFromState(state);
    expect(assessmentMissingForForward(state, [], values)).toBe(true);
    expect(
      assessmentMissingForForward(state, [], { card: { ...values.card, recommendation: "Mocny w SQL" } }),
    ).toBe(false);
    // Rekrutacja z pytaniami pyta o odpowiedzi, nie o ocenę.
    expect(assessmentMissingForForward(formState(), FORM_QUESTIONS, formDefaultsFromState(formState()))).toBe(false);
  });

  it("rekrutacja bez pytań: formularz nie zatrzymuje, gdy serwerowi wystarczy to, co już jest", () => {
    const empty = { card: {} };
    // Wartość z notatki zostaje mimo pustego pola.
    const fromNote = formState({ champion_profile: {} });
    fromNote.card.fields = { recommendation: { raw: "Polecam", source: "note" } };
    expect(assessmentMissingForForward(fromNote, [], empty)).toBe(false);
    // Odpowiedzi zapisane w notatce albo arkusz sprzed usunięcia pytań.
    const noteQuestions = formState({
      champion_profile: {},
      questions: [{ number: 1, question: "Java?", answer: "5 lat", source: "note" }],
    } as Partial<ReturnType<typeof formState>>);
    expect(assessmentMissingForForward(noteQuestions, [], empty)).toBe(false);
    expect(assessmentMissingForForward(formState({ champion_profile: {}, sheet: SAVED_SHEET }), [], empty)).toBe(false);
    // Pola nie da się wpisać (serwer go nie przyjmuje) — rozstrzyga serwer.
    const locked = formState({ champion_profile: {} });
    locked.card.editable_fields = ["availability"];
    expect(assessmentMissingForForward(locked, [], empty)).toBe(false);
  });

  it("pominięte pytania: domyślna notatka mówi prawdziwy powód (12.10.2026)", () => {
    const values = { ...formDefaultsFromState(formState()), skip_missing: true };
    expect(sheetFromValues(FORM_QUESTIONS, values).internal_note).toBe("Pominięte — przepięcie");
    expect(sheetFromValues(FORM_QUESTIONS, { ...values, skip_reason: "employed" }).internal_note).toBe(
      "Pominięte — osoba zatrudniona przez nas",
    );
    expect(sheetFromValues(FORM_QUESTIONS, { ...values, skip_reason: "earlier_screening" }).internal_note).toBe(
      "Pominięte — osoba po wcześniejszym screeningu",
    );
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

describe("rateNotRestoredMessage", () => {
  it("stawka wróciła — bez komunikatu", () => {
    expect(rateNotRestoredMessage({ rate_not_restored: false, rate_not_restored_reason: null }, "undo")).toBeNull();
  });

  it("wersja bez stawki — stawka została, zdanie zależy od trybu", () => {
    const result = { rate_not_restored: true, rate_not_restored_reason: "not_in_version" as const };
    expect(rateNotRestoredMessage(result, "undo")).toBe(
      "Cofnięto zapis — stawka kandydata została, zmień ją w formularzu.",
    );
    expect(rateNotRestoredMessage(result, "restore")).toMatch(/ta wersja jej nie miała/);
  });

  it("od „Zweryfikowany” stawką zarządza Delivery Lead", () => {
    expect(
      rateNotRestoredMessage({ rate_not_restored: true, rate_not_restored_reason: "managed_by_dl" }, "restore"),
    ).toMatch(/zarządza Delivery Lead/);
  });
});
