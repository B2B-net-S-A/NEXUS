import { describe, expect, it } from "vitest";

import {
  responsibilityCount,
  responsibilityGroups,
  responsibilityRows,
} from "../champion-responsibilities";

describe("responsibilityGroups", () => {
  it("lista z odczytu requestu: obszary z dwukropkiem i punkty pod nimi", () => {
    const text = [
      "Wymiana informacji w skali grupy:",
      "- Koordynacja interesariuszy biznesowych.",
      "- Uzgadnianie wymagań dla Single Customer View.",
      "Poprawa jakości danych:",
      "- Analizowanie wymagań RTS.",
    ].join("\n");

    expect(responsibilityGroups(text)).toEqual([
      {
        title: "Wymiana informacji w skali grupy",
        items: ["Koordynacja interesariuszy biznesowych.", "Uzgadnianie wymagań dla Single Customer View."],
      },
      { title: "Poprawa jakości danych", items: ["Analizowanie wymagań RTS."] },
    ]);
    expect(responsibilityCount(responsibilityGroups(text))).toBe(3);
  });

  it("punkty bez obszarów to jedna grupa bez tytułu, średnik w punkcie nie tnie", () => {
    expect(responsibilityGroups("- Projektowanie API; GraphQL i REST\n• Code review")).toEqual([
      { title: null, items: ["Projektowanie API; GraphQL i REST", "Code review"] },
    ]);
  });

  it("stary tekst bez listy tnie się jak dotąd na liniach i średnikach", () => {
    expect(responsibilityGroups("testy; code review\ndokumentacja")).toEqual([
      { title: null, items: ["testy", "code review", "dokumentacja"] },
    ]);
  });

  it("pusty tekst albo brak pola nie daje grup", () => {
    expect(responsibilityGroups("  ")).toEqual([]);
    expect(responsibilityGroups(undefined)).toEqual([]);
    expect(responsibilityGroups(null)).toEqual([]);
  });
});

describe("responsibilityRows", () => {
  it("pole rośnie z liczbą linii, od 2 do 14", () => {
    expect(responsibilityRows("")).toBe(2);
    expect(responsibilityRows(undefined)).toBe(2);
    expect(responsibilityRows("- a\n- b\n- c\n- d\n- e")).toBe(5);
    expect(responsibilityRows(Array.from({ length: 40 }, (_, i) => `- ${i}`).join("\n"))).toBe(14);
  });
});
