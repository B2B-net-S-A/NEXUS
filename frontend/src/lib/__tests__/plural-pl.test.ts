import { describe, expect, it } from "vitest";

import { countPl, pluralPl } from "@/lib/plural-pl";

describe("pluralPl", () => {
  it("zero bierze dopełniacz, nie mianownik mnogi", () => {
    // Regresja: wzorzec `n === 1 ? one : few` dawał „0 zamówienia".
    expect(countPl(0, "zamówienie", "zamówienia", "zamówień")).toBe(
      "0 zamówień",
    );
  });

  it("jedynka bierze mianownik", () => {
    expect(countPl(1, "zamówienie", "zamówienia", "zamówień")).toBe(
      "1 zamówienie",
    );
  });

  it("2-4 bierze mianownik mnogi", () => {
    for (const n of [2, 3, 4]) {
      expect(pluralPl(n, "wpis", "wpisy", "wpisów")).toBe("wpisy");
    }
  });

  it("5-21 bierze dopełniacz", () => {
    for (const n of [5, 9, 11, 15, 21]) {
      expect(pluralPl(n, "wpis", "wpisy", "wpisów")).toBe("wpisów");
    }
  });

  it("12-14 bierze dopełniacz mimo końcówki 2/3/4", () => {
    // Najczęstszy błąd w naiwnej implementacji „ostatnia cyfra 2-4 → few".
    for (const n of [12, 13, 14]) {
      expect(pluralPl(n, "wpis", "wpisy", "wpisów")).toBe("wpisów");
    }
  });

  it("22-24 wraca do mianownika mnogiego", () => {
    for (const n of [22, 23, 24, 102, 1002]) {
      expect(pluralPl(n, "wpis", "wpisy", "wpisów")).toBe("wpisy");
    }
  });

  it("112-114 znów dopełniacz (setki nie resetują wyjątku)", () => {
    for (const n of [112, 113, 114]) {
      expect(pluralPl(n, "wpis", "wpisy", "wpisów")).toBe("wpisów");
    }
  });

  it("odporne na liczby ujemne i niecałkowite", () => {
    expect(pluralPl(-1, "wpis", "wpisy", "wpisów")).toBe("wpis");
    expect(pluralPl(-5, "wpis", "wpisy", "wpisów")).toBe("wpisów");
    expect(pluralPl(2.7, "wpis", "wpisy", "wpisów")).toBe("wpisy");
  });
});
