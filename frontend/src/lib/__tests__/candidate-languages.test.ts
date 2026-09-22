import { describe, expect, it } from "vitest";

import {
  describeLanguageFilter,
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
});
