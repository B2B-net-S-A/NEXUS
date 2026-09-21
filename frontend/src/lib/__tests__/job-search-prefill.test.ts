import { describe, expect, it } from "vitest";
import {
  buildJobSearchPrefill,
  buildJobSearchQueryText,
  buildJobSearchTitleQuery,
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

  it("builds the query from title + seniority only, without description prose", () => {
    const prefill = buildJobSearchPrefill({
      title: "Data Engineer (ZOB-2846)",
      seniority: "senior",
      requirements: "Spark, Airflow",
      description: "Budowa hurtowni danych na GCP.",
    });
    expect(prefill.q).toBe("Data Engineer senior");
    expect(prefill.q).not.toContain("hurtowni");
    expect(prefill.q).not.toContain("Spark");
  });

  it("routes the query through hybrid (semantic), not boolean AND", () => {
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

  it("takes skills_must from the saved requirement labels, splitting alternatives", () => {
    const prefill = buildJobSearchPrefill(
      { title: "Dev", must_skills: ["Python", "Komunikatywność w zespole rozproszonym"] },
      ["java lub kotlin", "Spring"],
    );
    expect(prefill.skills_must).toEqual(["java", "kotlin", "Spring"]);
  });

  it("falls back to must_skills without prose entries longer than three words", () => {
    const prefill = buildJobSearchPrefill({
      title: "Dev",
      must_skills: ["Python", "Apache Kafka", "Doświadczenie w pracy z dużymi systemami"],
    });
    expect(prefill.skills_must).toEqual(["Python", "Apache Kafka"]);
  });

  it("does not filter by city for fully remote jobs", () => {
    const prefill = buildJobSearchPrefill({
      title: "Dev",
      location: "Warszawa",
      remote_policy: "remote",
    });
    expect(prefill.location_cities).toEqual([]);
  });
});

describe("wypełnienie z rekrutacji — test manualny 21.09.2026", () => {
  it("„lub okolice” i nawiasy nie są miastem", () => {
    expect(parseJobLocationCities("Warszawa lub okolice")).toEqual(["Warszawa"]);
    expect(parseJobLocationCities("Kraków i okolica (hybrydowo)")).toEqual(["Kraków"]);
    expect(parseJobLocationCities("Gdańsk + okolice")).toEqual(["Gdańsk"]);
  });

  it("alternatywy zapisane słowami to kilka miast", () => {
    expect(parseJobLocationCities("Warszawa lub Kraków")).toEqual(["Warszawa", "Kraków"]);
    expect(parseJobLocationCities("Warszawa / Remote")).toEqual(["Warszawa"]);
  });

  it("tytuł bez prefiksu klienta przed dwukropkiem", () => {
    expect(
      buildJobSearchTitleQuery({ title: "PKO BP: Programista Java Senior ZOB-2530" } as never),
    ).toBe("Programista Java Senior");
    expect(
      buildJobSearchTitleQuery({ title: "Nordea: BCCM RRP: SP1 Business Analyst" } as never),
    ).toBe("BCCM RRP: SP1 Business Analyst");
  });

  it("długi początek przed dwukropkiem zostaje (to nie prefiks klienta)", () => {
    const title = "Specjalista do spraw analizy danych: hurtownie";
    expect(buildJobSearchTitleQuery({ title } as never)).toBe(title);
  });
});
