import { describe, expect, it } from "vitest";
import {
  buildJobSearchPrefill,
  buildJobSearchQueryText,
  cleanQueryFragment,
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

describe("cleanQueryFragment", () => {
  it("collapses whitespace/newlines and strips HTML", () => {
    expect(
      cleanQueryFragment("Angular 14+\n<b>RxJS</b>\t TypeScript"),
    ).toBe("Angular 14+ RxJS TypeScript");
  });

  it("strips reference codes from a fragment", () => {
    expect(cleanQueryFragment("Rola dla projektu (ZOB-2846) w banku")).toBe(
      "Rola dla projektu w banku",
    );
  });

  it("returns empty for null / empty", () => {
    expect(cleanQueryFragment(null)).toBe("");
    expect(cleanQueryFragment("")).toBe("");
  });
});

describe("buildJobSearchQueryText", () => {
  const job = {
    title: "Data Engineer (ZOB-2846)",
    seniority: "senior",
    requirements: "Spark, Airflow, dbt",
    description:
      "Poszukujemy inżyniera danych do budowy hurtowni na GCP w zespole ML.",
  };

  it("enriches the query with title, seniority, requirements and description", () => {
    const q = buildJobSearchQueryText(job);
    expect(q).toContain("Data Engineer");
    expect(q).toContain("senior");
    expect(q).toContain("Spark");
    expect(q).toContain("hurtowni"); // from the description
  });

  it("never leaks the reference number into the query", () => {
    const q = buildJobSearchQueryText({
      title: "Data Engineer (ZOB-2846)",
      description: "Kandydat rozliczany na projekcie ZOB-2846.",
    });
    expect(q).not.toContain("ZOB-2846");
    expect(q).not.toContain("ZOB");
  });

  it("caps the query length under the backend's 500-char limit", () => {
    const q = buildJobSearchQueryText({
      title: "Dev",
      description: "słowo ".repeat(400), // ~2400 chars
    });
    expect(q.length).toBeLessThanOrEqual(480);
    expect(q.length).toBeGreaterThan(0);
  });

  it("falls back to the bare title when there is nothing to enrich", () => {
    expect(buildJobSearchQueryText({ title: "Backend Developer" })).toBe(
      "Backend Developer",
    );
  });
});

describe("buildJobSearchPrefill", () => {
  it("does not project an untyped job budget into the hourly candidate rate", () => {
    const prefill = buildJobSearchPrefill({
      title: "Data Engineer (ZOB-2846)",
      salary_min: 90,
      salary_max: 150,
    });
    expect(prefill.rate_hourly_min).toBeUndefined();
    expect(prefill.rate_hourly_max).toBeUndefined();
  });

  it("strips the ref number from the query", () => {
    const prefill = buildJobSearchPrefill({ title: "Data Engineer (ZOB-2846)" });
    expect(prefill.q).toBe("Data Engineer");
  });

  it("carries the job's description/requirements/seniority into the query", () => {
    const prefill = buildJobSearchPrefill({
      title: "Data Engineer (ZOB-2846)",
      seniority: "senior",
      requirements: "Spark, Airflow",
      description: "Budowa hurtowni danych na GCP.",
    });
    // Too-poor fix: the query is no longer just the bare title.
    expect(prefill.q).toContain("Data Engineer");
    expect(prefill.q).toContain("senior");
    expect(prefill.q).toContain("Spark");
    expect(prefill.q).toContain("hurtowni");
    // Negative control: the OLD behavior sent only the stripped title.
    expect(prefill.q).not.toBe("Data Engineer");
  });

  it("routes the enriched query through hybrid (semantic), not boolean AND", () => {
    // Description text in `q` is only recall-safe under hybrid retrieval;
    // in boolean mode `q` becomes a hard websearch_to_tsquery AND.
    const prefill = buildJobSearchPrefill({
      title: "Data Engineer",
      description: "Spark i Airflow na GCP.",
    });
    expect(prefill.search_mode).toBe("hybrid");
    // Negative control: the old prefill left search_mode at the boolean default.
    expect(prefill.search_mode).not.toBe("boolean");
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

  it("does NOT invent NULL-excluding hard filters from job metadata", () => {
    // seniority/languages/notice/start-date have no NULL-safe home, so the
    // mapper must not turn them into structured cuts that over-filter.
    const prefill = buildJobSearchPrefill({
      title: "Senior Data Engineer",
      seniority: "senior",
      requirements: "Angielski C1, notice 1 miesiąc, start ASAP",
    });
    expect(prefill.experience_years_min).toBeUndefined();
    expect(prefill.languages).toBeUndefined();
    expect(prefill.notice_period_max).toBeUndefined();
    expect(prefill.availability_date_before).toBeUndefined();
  });

  it("parses location into cities", () => {
    const prefill = buildJobSearchPrefill({
      title: "Dev",
      location: "Warszawa / Remote",
    });
    expect(prefill.location_cities).toEqual(["Warszawa"]);
  });
});
