import { describe, it, expect } from "vitest";
import {
  getEducationList,
  getLanguageList,
  getCandidateSummaryLine,
} from "@/components/v2/pages/candidate-profile-helpers";

describe("getEducationList", () => {
  it("returns clean entries from {school, degree, field, year} objects", () => {
    expect(
      getEducationList({
        education: [
          { school: "MIT", degree: "PhD", field: "CS", year: 2018 },
          { school: "  Harvard  ", degree: "MBA" },
        ],
      }),
    ).toEqual([
      { school: "MIT", degree: "PhD", field: "CS", year: 2018 },
      { school: "Harvard", degree: "MBA", field: null, year: null },
    ]);
  });

  it("drops entries with no school/degree/field", () => {
    expect(
      getEducationList({ education: [{ year: 2020 }, { school: "X" }] }),
    ).toEqual([{ school: "X", degree: null, field: null, year: null }]);
  });

  it("accepts string or number year", () => {
    expect(getEducationList({ education: [{ school: "A", year: "2019" }] })).toEqual(
      [{ school: "A", degree: null, field: null, year: "2019" }],
    );
  });

  it("returns [] on non-array / missing", () => {
    expect(getEducationList({ education: "BSc CS" })).toEqual([]);
    expect(getEducationList({ education: null })).toEqual([]);
    expect(getEducationList({})).toEqual([]);
  });
});

describe("getLanguageList", () => {
  it("handles {lang, level} objects", () => {
    expect(
      getLanguageList({
        languages: [
          { lang: "English", level: "C1" },
          { lang: "  Polski  ", level: "  native  " },
        ],
      }),
    ).toEqual([
      { lang: "English", level: "C1" },
      { lang: "Polski", level: "native" },
    ]);
  });

  it("handles plain strings", () => {
    expect(getLanguageList({ languages: ["English", "German"] })).toEqual([
      { lang: "English" },
      { lang: "German" },
    ]);
  });

  it("falls back to {name} key and nulls empty level", () => {
    expect(
      getLanguageList({ languages: [{ name: "French", level: "" }] }),
    ).toEqual([{ lang: "French", level: null }]);
  });

  it("drops entries without a language name + returns [] on non-array", () => {
    expect(getLanguageList({ languages: [{ level: "B2" }, ""] })).toEqual([]);
    expect(getLanguageList({ languages: null })).toEqual([]);
    expect(getLanguageList({})).toEqual([]);
  });
});

describe("getCandidateSummaryLine", () => {
  it("joins all available high-signal facts with ' · '", () => {
    expect(
      getCandidateSummaryLine({
        linkedin_current_title: "Senior Python Developer",
        years_it_experience: 7,
        city: "Warszawa",
        availability_status: "open_to_offers",
      }),
    ).toBe(
      "Senior Python Developer · 7+ lat · Warszawa · otwarty na oferty",
    );
  });

  it("skips missing segments", () => {
    expect(
      getCandidateSummaryLine({
        linkedin_current_title: "QA Engineer",
        city: "Kraków",
      }),
    ).toBe("QA Engineer · Kraków");
  });

  it("derives title from experience[0].role when no linkedin title", () => {
    expect(
      getCandidateSummaryLine({
        experience: [{ role: "Data Engineer" }],
        years_it_experience: 3,
      }),
    ).toBe("Data Engineer · 3 lat");
  });

  it("uses location when city is absent", () => {
    expect(getCandidateSummaryLine({ location: "Remote PL" })).toBe("Remote PL");
  });

  it("parses Traffit-style JSON location into human-readable label", () => {
    const blob = JSON.stringify({
      latitude: "52.235840",
      locality: "Warszawa",
      region1: "Mazowieckie",
      country: "Polska",
    });
    expect(getCandidateSummaryLine({ location: blob })).toBe(
      "Warszawa, Mazowieckie, Polska",
    );
  });

  it("returns null when nothing meaningful is available", () => {
    expect(getCandidateSummaryLine({})).toBeNull();
  });
});
