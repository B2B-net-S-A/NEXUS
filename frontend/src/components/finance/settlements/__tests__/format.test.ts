import { describe, expect, it } from "vitest";

import { autoAcceptText, defaultMonth, matchesFilter, mdText, monthLabel, nextMonths, pctText, recentMonths } from "../format";

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

describe("rozliczenia: automat przyjęcia bez uwag", () => {
  const info = { count: 1, workday: 3, from: "2026-11-04" };

  it("przed terminem podaje dzień, od którego automat bierze miesiąc", () => {
    expect(autoAcceptText(info, "2026-11-02")).toBe(
      "1 RCP bez uwag przyjmie się samo od 04.11 rano. RCP odesłane „Do poprawy” przyjmujecie ręcznie.",
    );
  });

  it("po terminie mówi o najbliższym porannym biegu i odmienia liczbę", () => {
    expect(autoAcceptText({ ...info, count: 3 }, "2026-11-04")).toContain("3 RCP bez uwag przyjmą się same przy najbliższym porannym biegu");
    expect(autoAcceptText({ ...info, count: 12 }, "2026-11-20")).toContain("12 RCP bez uwag przyjmie się samo");
    expect(autoAcceptText({ ...info, count: 22 }, "2026-11-20")).toContain("22 RCP bez uwag przyjmą się same");
  });

  it("bez RCP do przyjęcia mówi tylko, od kiedy działa", () => {
    expect(autoAcceptText({ ...info, count: 0 }, "2026-11-20")).toBe(
      "Automat przyjmuje RCP bez uwag od 3. dnia roboczego po miesiącu. Teraz nie ma czego przyjąć.",
    );
  });
});
