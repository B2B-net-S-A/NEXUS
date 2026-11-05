import { describe, expect, it } from "vitest";

import { dayMonth, deadlineText, offsetText, startLine } from "@/lib/start-docs-format";

describe("start-docs-format", () => {
  it("data ISO jako DD.MM, bez przesuwania strefy", () => {
    expect(dayMonth("2026-11-09")).toBe("09.11");
    expect(dayMonth("2026-11-09T23:30:00+00:00")).toBe("09.11");
    expect(dayMonth(null)).toBeNull();
  });

  it("termin mówi, czy jest po czasie", () => {
    expect(deadlineText("2026-10-29", "late")).toBe("po terminie od 29.10");
    expect(deadlineText("2026-11-05", "today")).toBe("termin dziś");
    expect(deadlineText("2026-11-20", "calm")).toBe("termin 20.11");
    expect(deadlineText(null, "calm")).toBeNull();
  });

  it("linia startu działa bez daty i bez terminu", () => {
    expect(startLine("2026-11-09", "2026-11-05", "today")).toBe("Start 09.11, termin dziś");
    expect(startLine("2026-11-09", null, "calm")).toBe("Start 09.11");
    expect(startLine(null, null, "calm")).toBe("Start jeszcze nieustalony");
  });

  it("odmienia dni robocze na liście klienta", () => {
    expect(offsetText(0)).toBe("W dniu startu");
    expect(offsetText(-1)).toBe("1 dzień roboczy przed startem");
    expect(offsetText(-2)).toBe("2 dni robocze przed startem");
    expect(offsetText(3)).toBe("3 dni robocze po starcie");
  });
});
