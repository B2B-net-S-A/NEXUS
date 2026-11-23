import { describe, expect, it } from "vitest";

import {
  clientChangeHref,
  groupChanges,
  lateGapCount,
  stashClientChangeText,
  takeClientChangeText,
  wordDiff,
  type ClientChange,
} from "@/lib/champion-client-change";

describe("groupChanges", () => {
  it("orders groups like the Brief blocks and keeps text fields apart", () => {
    const changes: ClientChange[] = [
      { id: "c1", op: "question_add", question: "Python?", ideal_answer: "", deal_breaker: "", quote: "" },
      { id: "c2", op: "text_edit", field: "project.about", label: "O projekcie", before: "a", after: "b", quote: "" },
      { id: "c3", op: "row_add", word: "Python", level: "must", quote: "" },
      { id: "c4", op: "row_remove", word: "SAFe", before: "nice", quote: "" },
      { id: "c5", op: "notes_append", text: "x", quote: "" },
    ];
    expect(groupChanges(changes).map((g) => [g.label, g.changes.map((c) => c.id)])).toEqual([
      ["Czego szukamy", ["c3", "c4"]],
      ["Niuanse", ["c5"]],
      ["Pytania na rozmowę", ["c1"]],
      ["O projekcie", ["c2"]],
    ]);
  });
});

describe("wordDiff", () => {
  it("marks only the changed words", () => {
    expect(wordDiff("Metodologia pracy: SAFe", "Metodologia pracy: Kanban")).toEqual([
      { kind: "same", text: "Metodologia pracy: " },
      { kind: "del", text: "SAFe" },
      { kind: "add", text: "Kanban" },
    ]);
  });

  it("handles empty sides", () => {
    expect(wordDiff("", "Nowe zdanie")).toEqual([{ kind: "add", text: "Nowe zdanie" }]);
    expect(wordDiff("Stare", "")).toEqual([{ kind: "del", text: "Stare" }]);
  });
});

describe("lateGapCount", () => {
  it("counts each process once across words", () => {
    const person = { candidate_id: 1, name: "A", stage: "after_screening" as const, owner_user_id: null };
    const missing = { before_screening: 0, after_screening: 1, at_client: 0 };
    expect(
      lateGapCount([
        { word: "Python", open_total: 3, missing, people: [{ ...person, process_id: 1 }] },
        { word: "SQL", open_total: 3, missing, people: [{ ...person, process_id: 1 }, { ...person, process_id: 2 }] },
      ]),
    ).toBe(2);
  });
});

describe("Jarvis hand-off", () => {
  it("passes the text once and builds the job link", () => {
    stashClientChangeText(7, "Python is now a must");
    expect(takeClientChangeText(7)).toBe("Python is now a must");
    expect(takeClientChangeText(7)).toBeNull();
    expect(clientChangeHref(7)).toBe("/jobs/7?tab=champion&ptab=brief&client_change=1");
  });
});
