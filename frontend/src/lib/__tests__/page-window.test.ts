import { describe, expect, it } from "vitest";

import { pageWindow } from "../page-window";

describe("pageWindow", () => {
  it("brak stron = pusty pasek", () => {
    expect(pageWindow(1, 0)).toEqual([]);
    expect(pageWindow(1, Number.NaN)).toEqual([]);
  });

  it("jedna i dwie strony — same numery", () => {
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(2, 2)).toEqual([1, 2]);
  });

  it("do siedmiu stron — wszystkie bez wielokropka", () => {
    expect(pageWindow(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("początek długiej listy: pięć pierwszych i ostatnia", () => {
    expect(pageWindow(1, 636)).toEqual([1, 2, 3, 4, 5, "gap", 636]);
    expect(pageWindow(4, 636)).toEqual([1, 2, 3, 4, 5, "gap", 636]);
  });

  it("środek: pierwsza, sąsiedzi bieżącej, ostatnia", () => {
    expect(pageWindow(5, 636)).toEqual([1, "gap", 4, 5, 6, "gap", 636]);
    expect(pageWindow(318, 636)).toEqual([1, "gap", 317, 318, 319, "gap", 636]);
  });

  it("koniec: pierwsza i pięć ostatnich", () => {
    expect(pageWindow(636, 636)).toEqual([1, "gap", 632, 633, 634, 635, 636]);
    expect(pageWindow(633, 636)).toEqual([1, "gap", 632, 633, 634, 635, 636]);
  });

  it("strona spoza zakresu jest przycinana", () => {
    expect(pageWindow(999, 8)).toEqual([1, "gap", 4, 5, 6, 7, 8]);
    expect(pageWindow(-3, 8)).toEqual([1, 2, 3, 4, 5, "gap", 8]);
  });

  it("bieżąca strona i jej sąsiedzi zawsze widoczni", () => {
    for (let page = 1; page <= 40; page += 1) {
      const items = pageWindow(page, 40);
      expect(items).toContain(page);
      if (page > 1) expect(items).toContain(page - 1);
      if (page < 40) expect(items).toContain(page + 1);
      expect(items.length).toBeLessThanOrEqual(7);
    }
  });
});
