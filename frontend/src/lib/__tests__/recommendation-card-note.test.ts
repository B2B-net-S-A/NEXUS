import { describe, expect, it } from "vitest";

import type { NoteProposal } from "@/lib/api/recommendationCards";
import {
  answerOriginBadge,
  cardFieldSource,
  looksLikeKeywords,
} from "@/lib/recommendation-card";
import {
  answerOrigin,
  buildApplyInput,
  initialReviewState,
  rateChangeWarning,
  selectedCount,
} from "@/lib/recommendation-card-note";

const PROPOSAL: NoteProposal = {
  fields: [
    {
      key: "rate",
      label: "Stawka",
      current: "150 zł/h",
      current_source: "manual",
      proposed: "165 zł/h netto B2B",
      quote: "stawka 165 netto b2b",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "location",
      label: "Lokalizacja",
      current: "Warszawa",
      current_source: "note",
      proposed: "Warszawa",
      quote: null,
      origin: "note_rule",
      changed: false,
    },
  ],
  answers: [
    {
      question_id: "q1",
      number: 1,
      question: "Kafka?",
      current: null,
      keywords: "kafka 3 lata",
      sentence: "Kandydat od 3 lat pracuje z Kafką.",
      problem: null,
    },
    {
      question_id: "q2",
      number: 2,
      question: "Dlaczego zmiana?",
      current: "Szuka dłuższego projektu.",
      keywords: "projekt się kończy",
      sentence: null,
      problem: "grudniu",
    },
  ],
  available: true,
  message: null,
  language: "pl",
  rate_change_notifies: true,
  text: "notatka",
};

describe("karta z notatki — przegląd", () => {
  it("na starcie zaznacza zmiany i odpowiedzi na pytania bez odpowiedzi", () => {
    const state = initialReviewState(PROPOSAL);
    expect(state.fields).toEqual({ rate: true, location: false });
    expect(state.answers.q1).toEqual({ selected: true, response: "Kandydat od 3 lat pracuje z Kafką." });
    // Pytanie ma już odpowiedź w arkuszu, a zdanie odrzucono — zostają hasła, odznaczone.
    expect(state.answers.q2).toEqual({ selected: false, response: "projekt się kończy" });
    expect(selectedCount(state)).toBe(2);
  });

  it("zapis niesie pochodzenie: zdanie Luny = phrased, poprawione = z notatki", () => {
    const state = initialReviewState(PROPOSAL);
    state.answers.q2 = { selected: true, response: "Projekt kandydata się kończy." };
    const input = buildApplyInput(PROPOSAL, state, "notatka.docx");
    expect(input.fields).toEqual({ rate: "165 zł/h netto B2B" });
    expect(input.field_origins).toEqual({ rate: "note_ai" });
    expect(input.source_name).toBe("notatka.docx");
    expect(input.answers.map((a) => [a.question_id, a.origin])).toEqual([
      ["q1", "phrased"],
      ["q2", "note_import"],
    ]);
  });

  it("puste odpowiedzi nie idą do zapisu", () => {
    const state = initialReviewState(PROPOSAL);
    state.answers.q1 = { selected: true, response: "  " };
    expect(buildApplyInput(PROPOSAL, state, null).answers).toEqual([]);
  });

  it("ostrzega o zmianie stawki tylko przy zaznaczonej stawce", () => {
    const state = initialReviewState(PROPOSAL);
    expect(rateChangeWarning(PROPOSAL, state)).toBe(true);
    state.fields.rate = false;
    expect(rateChangeWarning(PROPOSAL, state)).toBe(false);
  });

  it("answerOrigin porównuje bez białych znaków na brzegach", () => {
    expect(answerOrigin(" Zdanie. ", "Zdanie.")).toBe("phrased");
    expect(answerOrigin("Zdanie.", null)).toBe("note_import");
  });
});

describe("karta z notatki — podpisy i plakietki", () => {
  it("pole przyjęte z notatki mówi, skąd jest", () => {
    expect(cardFieldSource({ raw: "B2", source: "manual", origin: "note_ai", by_name: "Ola" })).toBe(
      "z notatki (AI) · Ola",
    );
    expect(cardFieldSource({ raw: "x", source: "manual", origin: "phrased" })).toBe("zdanie z haseł");
    expect(cardFieldSource({ raw: "x", source: "manual", by_name: "Ola" })).toBe("wpisał(a) Ola");
  });

  it("plakietki odpowiedzi", () => {
    expect(answerOriginBadge("phrased")).toBe("zdanie z haseł");
    expect(answerOriginBadge("note_import")).toBe("z notatki");
    expect(answerOriginBadge("manual")).toBeNull();
  });

  it("hasła rozpoznaje po braku kropki albo długości", () => {
    expect(looksLikeKeywords("kafka 3 lata prod, eventy")).toBe(true);
    expect(looksLikeKeywords("")).toBe(false);
    expect(
      looksLikeKeywords(
        "Kandydat od trzech lat pracuje z Kafką na produkcji przy zdarzeniach płatności w dużym banku.",
      ),
    ).toBe(false);
  });
});
