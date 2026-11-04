import { describe, expect, it } from "vitest";
import {
  dividerIndex,
  dividerTitle,
  hideUnknownPatch,
  knownSplitLabel,
  unknownFieldsBelow,
} from "@/lib/unknown-divider";

const K = { unknown_fields: [] };
const R = { unknown_fields: ["rate"] };
const L = { unknown_fields: ["location"] };
const E = { unknown_fields: ["experience"] };

describe("kreska nad osobami bez danych (D5, 19.10.2026)", () => {
  it("stoi nad pierwszą osobą bez danych przy układzie „z danymi, potem bez”", () => {
    expect(dividerIndex([K, K, R, L], { offset: 0, knownCount: 2 })).toBe(2);
  });

  it("bez braków albo przy brakach w środku (Mile widziane) — bez kreski", () => {
    expect(dividerIndex([K, K], { offset: 0, knownCount: 2 })).toBeNull();
    expect(dividerIndex([K, R, K, L], { offset: 0, knownCount: 2 })).toBeNull();
  });

  it("na górze strony tylko wtedy, gdy osoby z danymi skończyły się wcześniej", () => {
    expect(dividerIndex([R, L], { offset: 50, knownCount: 50 })).toBe(0);
    expect(dividerIndex([R, L], { offset: 100, knownCount: 50 })).toBeNull();
    // Nikt nie spełnia filtra z danymi — kreska nad całą pierwszą stroną.
    expect(dividerIndex([R, L], { offset: 0, knownCount: 0 })).toBe(0);
    expect(dividerIndex([R, L], { offset: 0, knownCount: null })).toBe(0);
    expect(dividerIndex([R, L], { offset: 50, knownCount: null })).toBeNull();
  });

  it("tytuł z pól pod kreską i „Ukryj”", () => {
    const rows = [K, R, L];
    expect(unknownFieldsBelow(rows, 1)).toEqual(["rate", "location"]);
    expect(dividerTitle(["rate", "location"])).toBe("Bez stawki albo miasta w profilu");
    expect(dividerTitle(["experience"])).toBe("Bez stażu w profilu");
    expect(hideUnknownPatch(["rate"])).toEqual({
      hideUnknownRate: true,
      hideUnknownLocation: true,
    });
    // Staż nie ma własnego przełącznika — „Ukryj” włącza globalne.
    expect(hideUnknownPatch(unknownFieldsBelow([E], 0))).toMatchObject({ hideUnknown: true });
  });
});

describe("licznik „N spełnia filtr · M bez danych”", () => {
  it("rozdziela trafienia od braków z formą czasownika", () => {
    expect(knownSplitLabel(25, 2)).toBe("2 spełniają filtr · 23 bez danych");
    expect(knownSplitLabel(25, 1)).toBe("1 spełnia filtr · 24 bez danych");
    expect(knownSplitLabel(30, 5)).toBe("5 spełnia filtr · 25 bez danych");
    expect(knownSplitLabel(30, 12)).toBe("12 spełnia filtr · 18 bez danych");
    expect(knownSplitLabel(30, 22)).toBe("22 spełniają filtr · 8 bez danych");
    expect(knownSplitLabel(12000, 0)).toMatch(/^0 spełnia filtr · 12\s000 bez danych$/);
  });

  it("bez liczby z serwera albo bez braków — zwykły licznik", () => {
    expect(knownSplitLabel(25, null)).toBeNull();
    expect(knownSplitLabel(25, undefined)).toBeNull();
    expect(knownSplitLabel(25, 25)).toBeNull();
  });
});
