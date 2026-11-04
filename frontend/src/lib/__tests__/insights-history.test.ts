import { describe, expect, it } from "vitest";

import { startsBeforeNexus, windowStartDay } from "@/lib/insights-history";

const TODAY = "2026-10-18"; // niedziela

describe("windowStartDay — początek okna z parametrów (Raporty nie mają `resolved`)", () => {
  it("liczy miesiąc, kwartał, rok, tydzień i dzień z przesunięciem", () => {
    expect(windowStartDay({ period: "month", offset: 0 }, null, TODAY)).toBe("2026-10-01");
    expect(windowStartDay({ period: "month", offset: -1 }, null, TODAY)).toBe("2026-09-01");
    expect(windowStartDay({ period: "month", offset: -10 }, null, TODAY)).toBe("2025-12-01");
    expect(windowStartDay({ period: "quarter", offset: -1 }, null, TODAY)).toBe("2026-07-01");
    expect(windowStartDay({ period: "year", offset: 0 }, null, TODAY)).toBe("2026-01-01");
    expect(windowStartDay({ period: "week", offset: 0 }, null, TODAY)).toBe("2026-10-12");
    expect(windowStartDay({ period: "day", offset: -7 }, null, TODAY)).toBe("2026-10-11");
  });

  it("własny zakres bierze `date_from`, a okno z backendu wygrywa", () => {
    expect(
      windowStartDay({ period: "custom", date_from: "2026-10-12", date_to: "2026-10-18" }, null, TODAY),
    ).toBe("2026-10-12");
    expect(
      windowStartDay({ period: "month", offset: 0 }, { start: "2026-08-01T00:00:00+02:00" }, TODAY),
    ).toBe("2026-08-01");
  });
});

describe("startsBeforeNexus", () => {
  it("bieżący tydzień od 12.10 — nie; bieżący miesiąc — tak", () => {
    expect(startsBeforeNexus({ period: "week", offset: 0 }, null, TODAY)).toBe(false);
    expect(startsBeforeNexus({ period: "month", offset: 0 }, null, TODAY)).toBe(true);
    expect(startsBeforeNexus({ period: "day", offset: -7 }, null, TODAY)).toBe(true);
  });
});
