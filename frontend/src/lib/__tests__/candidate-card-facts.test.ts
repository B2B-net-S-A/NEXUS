import { describe, expect, it } from "vitest";

import type {
  CandidateCardConversation,
  CandidateCardFact,
  CandidateCardNoteLink,
} from "@/lib/api/candidateCards";
import {
  cardConversationMeta,
  cardFactLine,
  cardFactOrigin,
  cardFactTitle,
  conversationsWithoutSheet,
  noteLinkSummary,
} from "@/lib/candidate-card-facts";

const fact = (extra: Partial<CandidateCardFact> = {}): CandidateCardFact => ({
  key: "rate",
  label: "Stawka",
  raw: "135 zł/h",
  value: 135,
  level: null,
  at: "2026-09-28T09:00:00+00:00",
  source: "note",
  author_name: "Marta Testowa",
  job_id: 10,
  job_title: "Senior Java Developer",
  ...extra,
});

const conversation = (extra: Partial<CandidateCardConversation> = {}): CandidateCardConversation => ({
  job_id: 10,
  job_title: "Senior Java Developer",
  client_name: "Bank Kappa",
  answered_at: "2026-09-28T09:00:00+00:00",
  author_name: "Marta Testowa",
  note_id: 1,
  from_traffit: false,
  question_count: 3,
  answers: [
    { number: 1, question: "Java 17+?", answer: "Java 21." },
    { number: 2, question: "Kolejki?", answer: "Kafka." },
  ],
  ...extra,
});

describe("ustalenia z kart rekomendacji w profilu", () => {
  it("ta sama stawka co w profilu = samo źródło z datą; inna = źródło z wartością z rozmowy", () => {
    expect(cardFactLine(fact(), 135)).toBe("rozmowa 28.09.2026");
    expect(cardFactLine(fact(), 155)).toBe("rozmowa 28.09.2026: 135 zł/h");
    // Profil bez stawki — karta mówi, co ustalono.
    expect(cardFactLine(fact(), null)).toBe("rozmowa 28.09.2026: 135 zł/h");
    // Stawka, której nie dało się odczytać jako liczby, zawsze niesie tekst.
    expect(cardFactLine(fact({ value: null, raw: "20 tys. zł/mies." }), 135)).toBe(
      "rozmowa 28.09.2026: 20 tys. zł/mies.",
    );
    expect(cardFactLine(undefined, 135)).toBeNull();
    expect(cardFactLine(fact({ raw: "  " }), 135)).toBeNull();
  });

  it("pole wpisane ręcznie i pole bez daty mają uczciwe źródło", () => {
    expect(cardFactOrigin(fact({ source: "manual" }))).toBe("wpisane w screeningu 28.09.2026");
    expect(cardFactOrigin(fact({ at: null }))).toBe("rozmowa");
    expect(cardFactTitle(fact())).toBe(
      "Z notatki z rozmowy · Marta Testowa · Senior Java Developer",
    );
    expect(cardFactTitle(fact({ source: "manual", author_name: null, job_title: null }))).toBe(
      "Wpisane w screeningu",
    );
  });

  it("długa wartość z rozmowy jest skracana w linii pod faktem", () => {
    const line = cardFactLine(
      fact({ key: "work_mode", value: null, raw: `hybrydowo, ${"bardzo długi opis ".repeat(10)}` }),
    );
    expect(line?.endsWith("…")).toBe(true);
    expect((line ?? "").length).toBeLessThan(110);
  });

  it("odpowiedzi z kart pokazujemy tylko dla rekrutacji bez arkusza screeningu", () => {
    const list = [conversation(), conversation({ job_id: 11 })];
    expect(conversationsWithoutSheet(list, new Set([10])).map((c) => c.job_id)).toEqual([11]);
    expect(conversationsWithoutSheet(undefined, new Set())).toEqual([]);
  });

  it("podpis rozmowy: data, ile pytań ma odpowiedź i skąd jest karta", () => {
    expect(cardConversationMeta(conversation())).toBe("28.09.2026 · 2 z 3 pytań · z notatki");
    expect(
      cardConversationMeta(
        conversation({
          from_traffit: true,
          question_count: 3,
          answered_at: "2025-02-03T10:00:00+00:00",
          answers: [
            { number: 1, question: "A?", answer: "a" },
            { number: 2, question: "B?", answer: "b" },
            { number: 3, question: "C?", answer: "c" },
          ],
        }),
      ),
    ).toBe("03.02.2025 · 3 pytania · z notatki wpisanej w Traffit");
    expect(cardConversationMeta(conversation({ answered_at: null, question_count: 0 }))).toBe(
      "2 pytania · z notatki",
    );
  });

  it("zdanie o tym, co z notatki trafiło do karty", () => {
    const link = (extra: Partial<CandidateCardNoteLink>): CandidateCardNoteLink => ({
      note_id: 1,
      job_id: 10,
      job_title: null,
      fields: [],
      field_labels: [],
      answers: 0,
      ...extra,
    });
    expect(
      noteLinkSummary(link({ field_labels: ["Stawka", "Dostępność", "Tryb pracy"], answers: 2 })),
    ).toBe("Do screeningu trafiło: stawka, dostępność, tryb pracy i 2 odpowiedzi");
    expect(noteLinkSummary(link({ field_labels: ["Stawka"] }))).toBe("Do screeningu trafiło: stawka");
    expect(noteLinkSummary(link({ answers: 1 }))).toBe("Do screeningu trafiło: 1 odpowiedź");
    expect(noteLinkSummary(link({}))).toBeNull();
  });
});
