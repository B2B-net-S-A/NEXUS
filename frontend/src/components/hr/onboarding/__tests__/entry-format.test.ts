import { describe, expect, it } from "vitest";

import type { LifecycleTask } from "@/lib/api/hr-lifecycle";

import { createLabel, entrySteps, missingReasonText, taskSourceLabel } from "../entry-format";

function task(patch: Partial<LifecycleTask>): LifecycleTask {
  return {
    id: 1,
    title: "Zadanie",
    category: "other",
    assignee_kind: "care_owner",
    assignee_user_id: null,
    assignee_name: null,
    due_date: null,
    status: "open",
    overdue: false,
    done_at: null,
    done_by_name: null,
    note: null,
    from_template: true,
    can_toggle: false,
    ...patch,
  };
}

describe("entrySteps", () => {
  it("dzieli zadania na kroki względem startu i liczy zamknięte", () => {
    const steps = entrySteps(
      [
        task({ id: 1, due_date: "2026-10-27", status: "done" }),
        task({ id: 2, due_date: "2026-11-02", status: "skipped" }),
        task({ id: 3, due_date: "2026-11-02" }),
        task({ id: 4, due_date: "2026-11-03" }),
        task({ id: 5, due_date: "2026-11-04" }),
        task({ id: 6, due_date: "2026-11-17" }),
        task({ id: 7, due_date: "2026-11-18" }),
        task({ id: 8, due_date: null }),
      ],
      "2026-11-03",
    );
    expect(steps.map((step) => [step.label, step.done, step.total])).toEqual([
      ["Przed startem", 2, 3],
      ["Dzień startu", 0, 1],
      ["Pierwsze 2 tygodnie", 0, 2],
      ["Do 30 dni", 0, 2],
    ]);
  });

  it("bez daty startu wszystko jest w jednym kroku", () => {
    const steps = entrySteps([task({ due_date: "2026-11-02" })], null);
    expect(steps).toEqual([{ key: "all", label: "Zadania", done: 0, total: 1 }]);
  });
});

describe("taskSourceLabel", () => {
  it("klient i forma mówią, skąd przyszły", () => {
    expect(taskSourceLabel(task({ source: "client", source_label: "Nordline Bank" }))).toBe(
      "Nordline Bank",
    );
    expect(taskSourceLabel(task({ source: "form", source_label: "B2B" }))).toBe("B2B");
    expect(taskSourceLabel(task({ source: "path" }))).toBe("ścieżka");
    expect(taskSourceLabel(task({ source: "manual" }))).toBe("dopisane");
    expect(taskSourceLabel(task({ source: undefined, from_template: false }))).toBe("dopisane");
  });
});

describe("missingReasonText", () => {
  it("każdy powód ma zdanie", () => {
    expect(missingReasonText("past_start")).toMatch(/minął/);
    expect(missingReasonText("no_path")).toMatch(/ścieżki/);
    expect(missingReasonText(null)).toBe("");
  });

  it("start za ponad 14 dni: lista powstanie sama, z datą, i można wcześniej", () => {
    expect(missingReasonText("not_yet", "2026-11-03")).toBe(
      "Lista zadań powstanie sama 14 dni przed startem — 03.11.2026. Możesz założyć ją wcześniej.",
    );
    // Data już minęła (przegląd jeszcze nie przeszedł) — bez daty w przeszłości.
    expect(missingReasonText("not_yet", null)).toBe(
      "Lista zadań powstanie sama przy najbliższym przeglądzie startów. Możesz założyć ją już teraz.",
    );
    expect(missingReasonText("not_yet")).not.toMatch(/ścieżki/);
  });
});

describe("createLabel", () => {
  it("przed startem „Załóż teraz”, po starcie „Załóż listę wejścia”", () => {
    expect(createLabel("not_yet")).toBe("Załóż teraz");
    expect(createLabel("past_start")).toBe("Załóż listę wejścia");
  });
});
