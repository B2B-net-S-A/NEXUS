import { describe, expect, it } from "vitest";

import type { ScreeningConversation } from "@/lib/api/screeningAnswers";
import { conversationTitle, filterConversations } from "@/lib/screening-conversations";

const conversation = (over: Partial<ScreeningConversation> = {}): ScreeningConversation => ({
  stage_id: 1,
  job_id: 10,
  job_title: "Senior Java Developer",
  client_name: "Bank Przykładowy",
  answered_at: "2026-09-30T10:00:00Z",
  answered_by_name: "Rekruter Testowy",
  overall_fit: "fit",
  match_percent: 80,
  answers: [
    {
      question_id: "q1",
      question_text: "Czy pracowałeś na mikroserwisach?",
      response: "Tak, Kafka i Spring Boot.",
      deal_breaker_hit: false,
      skipped: false,
    },
    { question_id: "q2", question_text: "Od kiedy dostępny?", response: "Od zaraz", deal_breaker_hit: false, skipped: false },
  ],
  experience_checks: [{ kind: "domains", name: "Bankowość", status: "confirmed", note: "2 lata" }],
  notes: "Dobra komunikacja.",
  internal_note: null,
  ...over,
});

describe("filterConversations", () => {
  const all = [conversation(), conversation({ stage_id: 2, job_id: 11, notes: "", experience_checks: [] })];

  it("pusta fraza oddaje wszystko bez zmian (nową listę)", () => {
    const out = filterConversations(all, "   ");
    expect(out).toEqual(all);
    expect(out).not.toBe(all);
  });

  it("zostawia tylko pasujące odpowiedzi — po pytaniu albo po odpowiedzi, bez wielkości liter", () => {
    const byAnswer = filterConversations(all, "KAFKA");
    expect(byAnswer).toHaveLength(2);
    expect(byAnswer[0].answers.map((a) => a.question_id)).toEqual(["q1"]);
    expect(byAnswer[0].experience_checks).toEqual([]);
    expect(byAnswer[0].notes).toBe("");

    const byQuestion = filterConversations(all, "dostępny");
    expect(byQuestion[0].answers.map((a) => a.question_id)).toEqual(["q2"]);
    // Numer pytania z arkusza zostaje — drugie pytanie nie staje się „pierwszym”.
    expect(byQuestion[0].answers[0].position).toBe(2);
  });

  it("trafia też w „sprawdzone w rozmowie” i w notatki; rozmowa bez trafienia odpada", () => {
    const byCheck = filterConversations(all, "bankowość");
    expect(byCheck.map((c) => c.stage_id)).toEqual([1]);
    expect(byCheck[0].answers).toEqual([]);
    expect(byCheck[0].experience_checks).toHaveLength(1);

    const byNote = filterConversations(all, "komunikacja");
    expect(byNote.map((c) => c.stage_id)).toEqual([1]);
    expect(byNote[0].notes).toBe("Dobra komunikacja.");

    const byInternal = filterConversations([conversation({ internal_note: "pominięte — przepięcie" })], "przepięcie");
    expect(byInternal[0].internal_note).toBe("pominięte — przepięcie");

    expect(filterConversations(all, "kubernetes")).toEqual([]);
  });

  it("odpowiedź na pytanie usunięte z profilu (bez tekstu pytania) nadal da się znaleźć", () => {
    const legacy = conversation({
      answers: [{ question_id: "q9", question_text: null, response: "Umowa B2B", deal_breaker_hit: false, skipped: false }],
    });
    expect(filterConversations([legacy], "b2b")[0].answers).toHaveLength(1);
  });
});

describe("conversationTitle", () => {
  it("rekrutacja i klient; bez klienta sama rekrutacja; bez tytułu numer", () => {
    expect(conversationTitle(conversation())).toBe("Senior Java Developer · Bank Przykładowy");
    expect(conversationTitle(conversation({ client_name: null }))).toBe("Senior Java Developer");
    expect(conversationTitle(conversation({ job_title: "  ", client_name: " " }))).toBe("Rekrutacja #10");
  });
});
