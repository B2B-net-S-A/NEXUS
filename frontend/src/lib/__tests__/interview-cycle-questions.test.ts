import { describe, expect, it } from "vitest";

import {
  MAX_DEBRIEF_QUESTIONS,
  debriefSummaryLine,
  mergeQuestions,
  questionsCountLabel,
  splitPastedQuestions,
} from "@/lib/interview-cycle";

describe("pytania klienta w debriefie", () => {
  it("dzieli wklejoną listę i usuwa numery oraz punktory", () => {
    expect(
      splitPastedQuestions("1. Kafka?\r\n2)  Spring   Boot\n\n- Docker\n• K8s\n* CI/CD\n– Java 17"),
    ).toEqual(["Kafka?", "Spring Boot", "Docker", "K8s", "CI/CD", "Java 17"]);
  });

  it("nie obcina liczby, która jest częścią pytania", () => {
    expect(splitPastedQuestions("Java 17 czy 21?\n2026 roadmapa")).toEqual([
      "Java 17 czy 21?",
      "2026 roadmapa",
    ]);
  });

  it("łączy powtórzenia bez wielkości liter i liczy pominięte ponad limit", () => {
    const current = Array.from({ length: MAX_DEBRIEF_QUESTIONS - 1 }, (_, i) => `P${i}`);
    const { questions, dropped } = mergeQuestions(current, ["p0", "Nowe", "Jeszcze jedno"]);
    expect(questions).toHaveLength(MAX_DEBRIEF_QUESTIONS);
    expect(questions.at(-1)).toBe("Nowe");
    expect(dropped).toBe(1);
  });

  it("odmienia liczbę pytań", () => {
    expect(questionsCountLabel(1)).toBe("1 pytanie klienta");
    expect(questionsCountLabel(3)).toBe("3 pytania klienta");
    expect(questionsCountLabel(5)).toBe("5 pytań klienta");
    expect(questionsCountLabel(12)).toBe("12 pytań klienta");
    expect(questionsCountLabel(22)).toBe("22 pytania klienta");
  });

  it("skrót debriefu", () => {
    expect(
      debriefSummaryLine({
        id: 1,
        overall_impression: 3,
        outcome: "medium",
        offer_acceptance: "no",
        acceptance_condition: null,
        questions_count: 0,
        no_client_questions: true,
      }),
    ).toBe("średnio · nie przyjmie · klient nie zadawał pytań");
  });
});
