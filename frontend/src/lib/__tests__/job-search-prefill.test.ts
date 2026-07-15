import { describe, expect, it } from "vitest";
import {
  buildJobSearchPrefill,
  extractSkillNames,
  parseJobLocationCities,
  stripJobReference,
} from "@/lib/job-search-prefill";

describe("stripJobReference", () => {
  it("removes a parenthesised reference code", () => {
    expect(stripJobReference("Data Engineer MID lub SENIOR (ZOB-2846)")).toBe(
      "Data Engineer MID lub SENIOR",
    );
  });

  it("removes a bracketed reference code", () => {
    expect(stripJobReference("Backend Dev [REQ 12345]")).toBe("Backend Dev");
  });

  it("removes a standalone reference token", () => {
    expect(stripJobReference("ZOB-2846 Data Engineer")).toBe("Data Engineer");
  });

  it("keeps non-numeric parentheticals", () => {
    expect(stripJobReference("Developer (Backend)")).toBe("Developer (Backend)");
  });

  it("falls back to the original title when stripping empties it", () => {
    expect(stripJobReference("ZOB-2846")).toBe("ZOB-2846");
  });

  it("collapses whitespace and trailing separators", () => {
    expect(stripJobReference("Senior Java  -  (ABC-99)")).toBe("Senior Java");
  });
});

describe("parseJobLocationCities", () => {
  it("splits a city / remote string and drops the mode token", () => {
    expect(parseJobLocationCities("Warszawa / Remote")).toEqual(["Warszawa"]);
  });

  it("splits multiple cities", () => {
    expect(parseJobLocationCities("Kraków, Wrocław")).toEqual([
      "Kraków",
      "Wrocław",
    ]);
  });

  it("drops Polish work-mode tokens", () => {
    expect(parseJobLocationCities("Gdańsk / Praca zdalna / Hybryda")).toEqual([
      "Gdańsk",
    ]);
  });

  it("returns empty for remote-only", () => {
    expect(parseJobLocationCities("Remote")).toEqual([]);
  });

  it("dedupes case-insensitively", () => {
    expect(parseJobLocationCities("Warszawa / warszawa")).toEqual(["Warszawa"]);
  });

  it("handles null / empty", () => {
    expect(parseJobLocationCities(null)).toEqual([]);
    expect(parseJobLocationCities("")).toEqual([]);
  });
});

describe("extractSkillNames", () => {
  it("reads a list of strings", () => {
    expect(extractSkillNames(["Python", "Go"])).toEqual(["Python", "Go"]);
  });

  it("reads a list of {name} objects", () => {
    expect(extractSkillNames([{ name: "Java" }, { name: "AWS" }])).toEqual([
      "Java",
      "AWS",
    ]);
  });

  it("ignores non-arrays and blanks", () => {
    expect(extractSkillNames(null)).toEqual([]);
    expect(extractSkillNames(["", "  "])).toEqual([]);
  });
});

describe("buildJobSearchPrefill", () => {
  it("maps a job's hourly rate to rate_hourly_* (not salary_*)", () => {
    const prefill = buildJobSearchPrefill({
      title: "Data Engineer (ZOB-2846)",
      salary_min: 90,
      salary_max: 150,
    });
    expect(prefill.rate_hourly_min).toBe(90);
    expect(prefill.rate_hourly_max).toBe(150);
    // Monthly salary fields must NOT be set from the hourly job rate.
    expect(prefill.salary_min).toBeUndefined();
    expect(prefill.salary_max).toBeUndefined();
  });

  it("strips the ref number from the query", () => {
    const prefill = buildJobSearchPrefill({ title: "Data Engineer (ZOB-2846)" });
    expect(prefill.q).toBe("Data Engineer");
  });

  it("does NOT send nice_skills as a hard filter", () => {
    const prefill = buildJobSearchPrefill({
      title: "Dev",
      must_skills: ["Python"],
      nice_skills: ["AWS", "Kafka"],
    });
    expect(prefill.skills_must).toEqual(["Python"]);
    expect(prefill.skills_any).toBeUndefined();
  });

  it("parses location into cities", () => {
    const prefill = buildJobSearchPrefill({
      title: "Dev",
      location: "Warszawa / Remote",
    });
    expect(prefill.location_cities).toEqual(["Warszawa"]);
  });
});
