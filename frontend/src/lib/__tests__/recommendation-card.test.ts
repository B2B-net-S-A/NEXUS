import { describe, expect, it } from "vitest";

import type { RecommendationCard } from "@/lib/api/recommendationCards";
import {
  answeredQuestions,
  boardCardBadge,
  cardChanges,
  cardFieldSource,
  cardFieldValue,
  cardStatusLabel,
  contactAttemptsLabel,
} from "@/lib/recommendation-card";

const card = (over: Partial<RecommendationCard> = {}): RecommendationCard => ({
  candidate_id: 1,
  job_id: 2,
  exists: true,
  fields: {
    rate: { raw: "135 zł/h", value: 135, source: "note", note_id: 7 },
    english: { raw: "bardzo dobry, C1", level: "C1", source: "manual", by_name: "Marta Testowa" },
  },
  previous: {},
  suggestions: {},
  questions: [],
  completeness: { status: "partial", filled: 2, total: 10, missing: ["motivation", "red_flags"] },
  labels: { rate: "Stawka", english: "Angielski", motivation: "Motywacja" },
  editable_fields: ["rate", "english", "motivation"],
  legacy_text: "",
  ...over,
});

describe("karta rekomendacji — prezentacja", () => {
  it("pokazuje odczytaną wartość zamiast surowego tekstu", () => {
    expect(cardFieldValue("english", card().fields.english)).toBe("C1");
    expect(cardFieldValue("worked_at_client", { raw: "Nie.", value: "no" })).toBe("nie pracował");
    expect(cardFieldValue("worked_at_client", { raw: "przez dostawcę" })).toBe("przez dostawcę");
    expect(cardFieldValue("red_flags", { raw: "brak", none: true })).toBe("brak");
    expect(cardFieldValue("rate", undefined)).toBe("");
  });

  it("mówi, skąd jest wartość", () => {
    expect(cardFieldSource(card().fields.rate)).toBe("z notatki");
    expect(cardFieldSource(card().fields.english)).toBe("wpisał(a) Marta Testowa");
    expect(cardFieldSource(undefined)).toBeNull();
  });

  it("podaje stan karty słowami", () => {
    expect(cardStatusLabel(card())).toBe("brakuje 2");
    expect(
      cardStatusLabel(card({ completeness: { status: "complete", filled: 10, total: 10, missing: [] } })),
    ).toBe("Karta gotowa");
  });

  it("liczy odpowiedzi na pytania", () => {
    expect(answeredQuestions(card())).toBeNull();
    expect(
      answeredQuestions(
        card({
          questions: [
            { number: 1, question: "Java?", answer: "Java 21", source: "sheet" },
            { number: 2, question: "Chmura?", answer: "", source: null },
          ],
        }),
      ),
    ).toBe("1 z 2 odpowiedzi");
  });

  it("wysyła tylko zmienione pola, a wyczyszczone jako null", () => {
    expect(
      cardChanges(card(), { rate: "135 zł/h", english: "", motivation: " szuka zmiany " }),
    ).toEqual({ english: null, motivation: "szuka zmiany" });
    expect(cardChanges(card(), { rate: " 135 zł/h " })).toEqual({});
  });

  it("odmienia próby kontaktu", () => {
    expect(contactAttemptsLabel(1)).toBe("1 próba kontaktu");
    expect(contactAttemptsLabel(3)).toBe("3 próby kontaktu");
    expect(contactAttemptsLabel(5)).toBe("5 prób kontaktu");
    expect(contactAttemptsLabel(12)).toBe("12 prób kontaktu");
    expect(contactAttemptsLabel(22)).toBe("22 próby kontaktu");
  });
});

describe("plakietka karty na tablicy", () => {
  it("pokazuje stan karty w Screeningu, Zweryfikowanym i QC CV", () => {
    expect(boardCardBadge({ status: "complete", missing: 0, answers: 3 }, 0, "verified")?.label).toBe(
      "Karta gotowa",
    );
    expect(boardCardBadge({ status: "partial", missing: 2, answers: 0 }, 0, "screening")).toMatchObject({
      label: "Karta: brakuje 2",
      tone: "wait",
    });
  });

  it("bez karty mówi o próbach kontaktu tylko w Screeningu", () => {
    expect(boardCardBadge(null, 3, "screening")?.label).toBe("3 próby kontaktu");
    expect(boardCardBadge(null, 0, "screening")?.label).toBe("Bez karty");
    expect(boardCardBadge({ status: "empty", missing: 10, answers: 0 }, 2, "cv_qc")?.label).toBe(
      "Bez karty",
    );
  });

  it("nie zaśmieca pozostałych kolumn", () => {
    for (const column of ["new", "cv_sent", "client_interview", "hired", null]) {
      expect(boardCardBadge({ status: "partial", missing: 2, answers: 0 }, 1, column)).toBeNull();
    }
  });
});
