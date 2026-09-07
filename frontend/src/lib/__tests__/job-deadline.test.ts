import { describe, expect, it } from "vitest";

import { classifyJobDeadline } from "@/lib/job-deadline";

const TODAY = new Date(2026, 8, 7); // 07.09.2026, lokalnie (miesiące 0-indeksowane)

describe("classifyJobDeadline", () => {
  it("brak deadline'u → \"none\", bez dni", () => {
    expect(classifyJobDeadline(null, TODAY)).toEqual({
      urgency: "none",
      daysLeft: null,
    });
    expect(classifyJobDeadline(undefined, TODAY)).toEqual({
      urgency: "none",
      daysLeft: null,
    });
  });

  it("data dzisiejsza → \"soon\", 0 dni", () => {
    expect(classifyJobDeadline("2026-09-07", TODAY)).toEqual({
      urgency: "soon",
      daysLeft: 0,
    });
  });

  it("dokładnie 7 dni do przodu → nadal \"soon\" (granica włącznie)", () => {
    expect(classifyJobDeadline("2026-09-14", TODAY)).toEqual({
      urgency: "soon",
      daysLeft: 7,
    });
  });

  it("8 dni do przodu → \"normal\", poza progiem", () => {
    expect(classifyJobDeadline("2026-09-15", TODAY)).toEqual({
      urgency: "normal",
      daysLeft: 8,
    });
  });

  it("wczoraj → \"overdue\", ujemne dni", () => {
    expect(classifyJobDeadline("2026-09-06", TODAY)).toEqual({
      urgency: "overdue",
      daysLeft: -1,
    });
  });

  it("nieparsowalna data → \"none\", nie wywala się", () => {
    expect(classifyJobDeadline("not-a-date", TODAY)).toEqual({
      urgency: "none",
      daysLeft: null,
    });
  });
});
