/**
 * Widok „Screening” tylko do odczytu (09.10.2026) — złożenie wierszy pytań
 * i krótkie napisy. Dane fikcyjne.
 */

import { describe, expect, it } from "vitest";

import type { ScreeningFormQuestion, ScreeningFormState } from "@/lib/api/screeningForm";
import {
  screeningAnsweredLabel,
  screeningDealBreakerWarning,
  screeningFieldHint,
  screeningFieldsLabel,
  screeningFormHref,
  screeningSectionSummary,
  screeningSummaryRows,
} from "@/lib/screening-summary";

const question = (over: Partial<ScreeningFormQuestion>): ScreeningFormQuestion => ({
  number: 1,
  question: "Ile lat pracujesz z Javą?",
  answer: "",
  source: null,
  question_id: "q1",
  deal_breaker: null,
  deal_breaker_hit: false,
  ...over,
});

const sheet = (answers: NonNullable<ScreeningFormState["sheet"]>["answers"]): ScreeningFormState["sheet"] => ({
  answers,
  overall_fit: "fit",
  notes: "",
});

describe("screeningSummaryRows", () => {
  it("bierze pytania z serwera: odpowiedź z arkusza, z notatki albo brak", () => {
    const rows = screeningSummaryRows({
      sheet: sheet([{ question_id: "q1", response: "6 lat", deal_breaker_hit: false, question_text: "Ile lat pracujesz z Javą?" }]),
      questions: [
        question({ answer: "6 lat", source: "sheet", deal_breaker: "Poniżej 2 lat" }),
        question({ number: 2, question_id: "q2", question: "Kafka?", answer: "Tak", source: "note" }),
        question({ number: 3, question_id: "q3", question: "Chmura?" }),
      ],
    });
    expect(rows.map((row) => [row.position, row.question_text, row.response, row.source])).toEqual([
      [1, "Ile lat pracujesz z Javą?", "6 lat", "sheet"],
      [2, "Kafka?", "Tak", "note"],
      [3, "Chmura?", "", null],
    ]);
    expect(rows[0].deal_breaker).toBe("Poniżej 2 lat");
  });

  it("po edycji profilu pokazuje pytanie z chwili odpowiedzi i nie dokleja cudzego „Odpada, gdy…”", () => {
    // Identyfikatory pytań są pozycyjne: „q1” znaczy dziś inne pytanie niż wtedy.
    const [row] = screeningSummaryRows({
      sheet: sheet([{ question_id: "q1", response: "B2", deal_breaker_hit: false, question_text: "Jaki masz angielski?" }]),
      questions: [question({ answer: "B2", source: "sheet", deal_breaker: "Poniżej 2 lat" })],
    });
    expect(row.question_text).toBe("Jaki masz angielski?");
    expect(row.deal_breaker).toBeNull();
  });

  it("pytanie pominięte przy przepięciu jest pominięte, a nie „bez odpowiedzi”", () => {
    const [row] = screeningSummaryRows({
      sheet: sheet([{ question_id: "q1", response: "", deal_breaker_hit: false, skipped: true }]),
      questions: [question({})],
    });
    expect(row.skipped).toBe(true);
  });

  it("odpowiedź z notatki wygrywa z pominięciem w arkuszu", () => {
    const [row] = screeningSummaryRows({
      sheet: sheet([{ question_id: "q1", response: "", deal_breaker_hit: false, skipped: true }]),
      questions: [question({ answer: "5 lat", source: "note" })],
    });
    expect(row.skipped).toBe(false);
    expect(row.response).toBe("5 lat");
  });

  it("odpowiedzi na pytania usunięte z profilu zostają na końcu", () => {
    const rows = screeningSummaryRows({
      sheet: sheet([
        { question_id: "q1", response: "6 lat", deal_breaker_hit: false },
        { question_id: "q9", response: "Tak, od 2019", deal_breaker_hit: false, question_text: null },
        { question_id: "q8", response: "  ", deal_breaker_hit: false },
      ]),
      questions: [question({ answer: "6 lat", source: "sheet" })],
    });
    expect(rows.map((row) => [row.question_id, row.position])).toEqual([
      ["q1", 1],
      ["q9", 2],
    ]);
  });

  it("rekrutacja bez pytań w profilu pokazuje pytania zapisane w notatce", () => {
    const rows = screeningSummaryRows({
      sheet: null,
      questions: [question({ question_id: null, question: "Dostępność?", answer: "od zaraz", source: "note" })],
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].question_id).toBe("note:1");
    expect(rows[0].response).toBe("od zaraz");
  });

  it("starszy serwer (bez `questions`) daje same odpowiedzi arkusza", () => {
    const rows = screeningSummaryRows({
      sheet: sheet([{ question_id: "q1", response: "6 lat", deal_breaker_hit: false, question_text: "Java?" }]),
    });
    expect(rows).toEqual([expect.objectContaining({ question_id: "q1", response: "6 lat", position: 1 })]);
    expect(screeningSummaryRows({ sheet: null })).toEqual([]);
  });
});

describe("napisy widoku", () => {
  it("ostrzega o naruszonym „Odpada, gdy…” z numerami pytań", () => {
    expect(screeningDealBreakerWarning([{ question_id: "q1", position: 1 }])).toBeNull();
    expect(screeningDealBreakerWarning([{ question_id: "q2", position: 2, deal_breaker_hit: true }])).toBe(
      "Odpowiedź na pytanie 2 narusza „Odpada, gdy…”.",
    );
    expect(
      screeningDealBreakerWarning([
        { question_id: "q1", position: 1, deal_breaker_hit: true },
        { question_id: "q3", position: 3, deal_breaker_hit: true },
      ]),
    ).toBe("Odpowiedzi na pytania 1, 3 naruszają „Odpada, gdy…”.");
  });

  it("liczy pytania z odpowiedzią", () => {
    expect(screeningAnsweredLabel([])).toBeNull();
    expect(
      screeningAnsweredLabel([
        { question_id: "q1", response: "tak" },
        { question_id: "q2", response: "  " },
      ]),
    ).toBe("1 z 2");
  });

  it("puste pole podpowiada wartość z poprzedniej próby, potem z profilu", () => {
    const card = { previous: { work_mode: { raw: " zdalnie " } }, suggestions: { nationality: "polska" } };
    expect(screeningFieldHint(card, "work_mode")).toBe("zdalnie");
    expect(screeningFieldHint(card, "nationality")).toBe("polska");
    expect(screeningFieldHint(card, "english")).toBeNull();
  });

  it("stan pól mówi o polach, nie o „karcie”", () => {
    expect(screeningFieldsLabel(null)).toBe("puste pola");
    expect(screeningFieldsLabel({ status: "empty", missing: 10 })).toBe("puste pola");
    expect(screeningFieldsLabel({ status: "partial", missing: 3 })).toBe("brakuje 3");
    expect(screeningFieldsLabel({ status: "complete", missing: 0 })).toBe("komplet pól");
  });

  it("zwinięta sekcja doku łączy ocenę rekrutera ze stanem pól", () => {
    expect(screeningSectionSummary(null, null)).toBe("Pytania, warunki i ocena");
    expect(screeningSectionSummary({ status: "partial", missing: 2, answers: 0 }, null)).toBe("brakuje 2");
    expect(screeningSectionSummary({ status: "complete", missing: 0, answers: 3 }, "fit")).toBe("Pasuje · komplet pól");
    expect(screeningSectionSummary(undefined, "miss")).toBe("Nie pasuje · puste pola");
  });

  it("link do formularza otwiera panel osoby na „Screeningu”", () => {
    expect(screeningFormHref(31, 21)).toBe("/jobs/31?candidate=21&panel=screening");
  });
});
