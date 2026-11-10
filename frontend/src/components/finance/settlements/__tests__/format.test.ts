import { describe, expect, it } from "vitest";

import { defaultMonth, matchesFilter, mdText, monthLabel, nextMonths, pctText, recentMonths } from "../format";

describe("rozliczenia: miesiące", () => {
  it("domyślnie poprzedni miesiąc, także na przełomie roku", () => {
    expect(defaultMonth("2026-11-09")).toBe("2026-10");
    expect(defaultMonth("2027-01-02")).toBe("2026-12");
  });

  it("lista wstecz i w przód przez granicę roku", () => {
    expect(recentMonths("2027-02-15", 3)).toEqual(["2027-02", "2027-01", "2026-12"]);
    expect(nextMonths("2026-11-30", 3)).toEqual(["2026-11", "2026-12", "2027-01"]);
  });

  it("nazwa miesiąca po polsku", () => {
    expect(monthLabel("2026-10")).toBe("październik 2026");
  });
});

describe("rozliczenia: filtry listy", () => {
  it("„Do zrobienia” to RCP do decyzji Finansów albo faktura z inną kwotą", () => {
    expect(matchesFilter("todo", "ok", false)).toBe(true);
    expect(matchesFilter("todo", "no_md", false)).toBe(true);
    expect(matchesFilter("todo", "accepted", true)).toBe(true);
    expect(matchesFilter("todo", "accepted", false)).toBe(false);
    expect(matchesFilter("todo", "missing", false)).toBe(false);
    expect(matchesFilter("todo", "needs_fix", false)).toBe(false);
  });

  it("pozostałe filtry po samym stanie", () => {
    expect(matchesFilter("missing", "missing", false)).toBe(true);
    expect(matchesFilter("needs_fix", "needs_fix", false)).toBe(true);
    expect(matchesFilter("accepted", "warnings", false)).toBe(false);
    expect(matchesFilter("all", "missing", true)).toBe(true);
  });
});

describe("rozliczenia: liczby", () => {
  it("brak wartości to kreska, nie zero", () => {
    expect(mdText(null)).toBe("–");
    expect(pctText(null)).toBeNull();
  });

  it("MD z przecinkiem, do trzech miejsc", () => {
    expect(mdText("21.750")).toBe("21,75");
    expect(pctText("8.8")).toBe("8,8%");
  });
});
