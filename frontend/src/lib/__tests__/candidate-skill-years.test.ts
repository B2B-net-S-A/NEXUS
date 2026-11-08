import { describe, expect, it } from "vitest";
import {
  formatMonths,
  knownSkillYears,
  missingSkillYears,
  parseSkillYearsEntries,
  parseSkillYearsEntry,
  skillYearsEntries,
  skillYearsRowLabel,
  yearsWord,
} from "@/lib/candidate-skill-years";
import { decodeFilters, encodeFilters, filtersToApiParams, DEFAULT_FILTERS } from "@/lib/url-filters";
import { dividerTitle, hideUnknownPatch, unknownFieldsBelow } from "@/lib/unknown-divider";
import { unknownFieldBadges } from "@/lib/candidate-search-semantics";

describe("wpis „technologia:lata”", () => {
  it("czyta technologię z dwukropkiem w nazwie i spacjami", () => {
    expect(parseSkillYearsEntry(" ASP.NET Core : 4")).toEqual({ skill: "ASP.NET Core", years: 4 });
    expect(parseSkillYearsEntry("C++:2")).toEqual({ skill: "C++", years: 2 });
  });

  it.each(["Java", ":3", "Java:", "Java:0", "Java:31", "Java:trzy"])("odrzuca „%s”", (raw) => {
    expect(parseSkillYearsEntry(raw)).toBeNull();
  });

  it("ta sama technologia dwa razy = wyższy próg, najwyżej 5 wierszy", () => {
    expect(parseSkillYearsEntries(["Java:2", "java:5"])).toEqual([{ skill: "Java", years: 5 }]);
    expect(parseSkillYearsEntries(["A:1", "B:1", "C:1", "D:1", "E:1", "F:1"])).toHaveLength(5);
  });

  it("niedokończony wiersz z okienka nie trafia do filtrów", () => {
    expect(
      skillYearsEntries([
        { skill: "Java", years: 3 },
        { skill: "  ", years: 3 },
        { skill: "Kafka", years: 40 },
      ]),
    ).toEqual(["Java:3", "Kafka:30"]);
  });
});

describe("opis lat po polsku", () => {
  it.each([
    [1, "1 rok"],
    [3, "3 lata"],
    [5, "5 lat"],
    [12, "12 lat"],
    [22, "22 lata"],
  ])("%i → %s", (n, text) => {
    expect(yearsWord(n)).toBe(text);
  });

  it.each([
    [7, "7 mies."],
    [24, "2 lata"],
    [80, "6 lat 8 mies."],
    [232, "19 lat 4 mies."],
  ])("%i miesięcy → %s", (months, text) => {
    expect(formatMonths(months)).toBe(text);
  });

  it("chip filtru", () => {
    expect(skillYearsRowLabel({ skill: "Java", years: 3 })).toBe("Java ≥ 3 lata");
    expect(skillYearsRowLabel({ skill: "Kafka", years: 1 })).toBe("Kafka ≥ 1 rok");
  });

  it("wiersz listy: lata tylko z datami, braki osobno", () => {
    const entries = [
      { skill: "Java", years_min: 3, months: 80, source: "cv_roles" as const },
      { skill: "Kafka", years_min: 2, months: null, source: null },
    ];
    expect(knownSkillYears(entries)).toEqual([{ skill: "Java", text: "6 lat 8 mies." }]);
    expect(missingSkillYears(entries)).toEqual(["Kafka"]);
    expect(knownSkillYears(null)).toEqual([]);
  });
});

describe("adres i API", () => {
  it("adres w obie strony, zły wpis z ręki znika", () => {
    const f = { ...DEFAULT_FILTERS, skillYears: ["Java:3", "Kafka:2"], hideUnknownSkillYears: true };
    const qs = encodeFilters(f);
    expect(qs.get("sky")).toBe("Java:3|Kafka:2");
    expect(qs.get("husy")).toBe("1");
    expect(decodeFilters(qs)).toMatchObject({
      skillYears: ["Java:3", "Kafka:2"],
      hideUnknownSkillYears: true,
    });
    expect(decodeFilters(new URLSearchParams("sky=Java:3|zle|Go:99")).skillYears).toEqual([
      "Java:3",
    ]);
  });

  it("samo „ukryj” bez wierszy nie idzie ani do adresu, ani do API", () => {
    const f = { ...DEFAULT_FILTERS, hideUnknownSkillYears: true };
    expect(encodeFilters(f).get("husy")).toBeNull();
    expect(filtersToApiParams(f, 1).hide_unknown_skill_years).toBeUndefined();
  });

  it("API dostaje powtarzany `skill_years`", () => {
    const params = filtersToApiParams({ ...DEFAULT_FILTERS, skillYears: ["Java:3"] }, 1);
    expect(params.skill_years).toEqual(["Java:3"]);
  });
});

describe("osoby bez dat w CV", () => {
  it("plakietka i kreska mówią o datach w CV, „Ukryj” włącza przełącznik lat", () => {
    expect(unknownFieldBadges(["skill_years"]).map((b) => b.label)).toEqual(["bez dat w CV"]);
    const rows = [{ unknown_fields: [] }, { unknown_fields: ["skill_years"] }];
    expect(unknownFieldsBelow(rows, 1)).toEqual(["skill_years"]);
    expect(dividerTitle(["skill_years"])).toBe("Bez dat przy technologii w CV");
    expect(dividerTitle(["rate", "skill_years"])).toBe(
      "Bez stawki albo dat przy technologii w profilu",
    );
    expect(hideUnknownPatch(["skill_years"])).toMatchObject({ hideUnknownSkillYears: true });
    expect(hideUnknownPatch(["rate"])).not.toHaveProperty("hideUnknownSkillYears");
  });
});
