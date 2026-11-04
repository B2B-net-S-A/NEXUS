import { describe, expect, it } from "vitest";

import {
  LANGUAGE_OPTIONS,
  describeLanguageFilter,
  isListedLanguageCode,
  otherLanguageCode,
  searchLanguageOptions,
  languageFilterToUnified,
  normalizeLanguageFilters,
  parseLanguageFilter,
  unifiedLanguageToFilter,
} from "@/lib/candidate-languages";

describe("candidate-languages", () => {
  it("czyta kod i poziom bez względu na wielkość liter", () => {
    expect(parseLanguageFilter("EN:b2")).toEqual({ code: "en", level: "B2" });
    expect(parseLanguageFilter("pl:NATIVE")).toEqual({ code: "pl", level: "native" });
    expect(parseLanguageFilter("de")).toEqual({ code: "de", level: null });
    expect(parseLanguageFilter("de:")).toEqual({ code: "de", level: null });
  });

  it("odrzuca wpisy, których API nie zrozumie", () => {
    expect(parseLanguageFilter("xx:Z9")).toBeNull();
    expect(parseLanguageFilter("english:B2")).toBeNull();
    expect(parseLanguageFilter("en:B2:C1")).toBeNull();
    expect(normalizeLanguageFilters(["en:B2", "EN:C1", "b4d", "de"])).toEqual(["en:B2", "de"]);
  });

  it("etykieta chipu po polsku", () => {
    expect(describeLanguageFilter("en:B2")).toBe("angielski min. B2");
    expect(describeLanguageFilter("de")).toBe("niemiecki");
    expect(describeLanguageFilter("pl:native")).toBe("polski ojczysty");
  });

  it("kształt wyszukiwarki w obie strony", () => {
    expect(languageFilterToUnified("en:B2")).toEqual({ code: "EN", min_level: "B2" });
    expect(languageFilterToUnified("de")).toEqual({ code: "DE" });
    expect(unifiedLanguageToFilter({ code: "EN", min_level: "b2" })).toBe("en:B2");
    expect(unifiedLanguageToFilter({ code: "DE" })).toBe("de");
    expect(unifiedLanguageToFilter("EN")).toBeNull();
  });

  it("jedna lista ~30 języków z unikalnymi kodami", () => {
    expect(LANGUAGE_OPTIONS.length).toBeGreaterThanOrEqual(30);
    const codes = LANGUAGE_OPTIONS.map((o) => o.code);
    expect(new Set(codes).size).toBe(codes.length);
  });

  it("szuka po nazwie bez polskich znaków i po kodzie", () => {
    expect(searchLanguageOptions("slowack").map((o) => o.code)).toEqual(["sk"]);
    expect(searchLanguageOptions("ŁOTEW").map((o) => o.code)).toEqual(["lv"]);
    expect(searchLanguageOptions("ja").map((o) => o.code)).toContain("ja");
    expect(searchLanguageOptions("  ")).toHaveLength(LANGUAGE_OPTIONS.length);
  });

  it("kod „Innego…” wynika z nazwy, a lista zna tylko swoje kody", () => {
    expect(otherLanguageCode("Kataloński")).toBe("katalonski");
    expect(otherLanguageCode("  Łużycki górny ")).toBe("luzycki-gorny");
    expect(isListedLanguageCode("EN")).toBe(true);
    expect(isListedLanguageCode("katalonski")).toBe(false);
  });
});
