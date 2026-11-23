import { describe, expect, it } from "vitest";

import type { ChampionProfile } from "@/lib/api";
import { flagKeyTaskQuestion, keyTaskOf, keyTaskQuestionIndex } from "@/lib/champion-key-task";

const q = (id: string, key_task?: boolean) => ({ id, question: `Pytanie ${id}?`, ideal_answer: "", deal_breaker: "", key_task });

describe("champion-key-task", () => {
  it("bez wpisanego zadania nie ma czego pokazać (profile sprzed 23.11.2026)", () => {
    expect(keyTaskOf({ project: { about: "x", responsibilities: "" }, screening_questions: [q("q1", true)] })).toBeNull();
    expect(keyTaskOf({})).toBeNull();
  });

  it("zadanie z pytaniem, które je sprawdza, albo bez wskazanego pytania", () => {
    const project = { about: "", responsibilities: "", key_task: "  Migracja rozliczeń.  " };
    expect(keyTaskOf({ project, screening_questions: [q("q1"), q("q2", true)] })).toEqual({
      task: "Migracja rozliczeń.",
      questionIndex: 1,
    });
    expect(keyTaskOf({ project, screening_questions: [q("q1")] })).toEqual({ task: "Migracja rozliczeń.", questionIndex: null });
  });

  it("zaznaczenie pytania zdejmuje oznaczenie z pozostałych", () => {
    const questions: ChampionProfile["screening_questions"] = [q("q1", true), q("q2"), q("q3")];
    const flagged = flagKeyTaskQuestion(questions, 2);
    expect(flagged.map((x) => x.key_task)).toEqual([false, false, true]);
    expect(keyTaskQuestionIndex(flagged)).toBe(2);
    expect(keyTaskQuestionIndex([q("q1")])).toBeNull();
  });
});
