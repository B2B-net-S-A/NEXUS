import { describe, expect, it } from "vitest";

import type { CareerJobResponse } from "../api";
import { jobPostingJsonLd, jsonLdString } from "../jobPosting";

function data(overrides: Partial<CareerJobResponse> = {}): CareerJobResponse {
  return {
    status: "open",
    recruiter: { first_name: "Marta", slug: "marta-n" },
    theme: "terminal",
    published_at: "2026-10-18",
    job: {
      slug: "senior-java-developer-k7q2",
      title: "Senior Java Developer",
      subtitle: "rozwój platformy płatności",
      about: "Zespół 8 osób.",
      must: [{ name: "Java 17", note: null }],
      nice: ["Kafka"],
      params: {
        city: "Warszawa",
        remote_policy: "hybrid",
        onsite_days_per_week: 2,
        seniority: "senior",
        contract: "B2B",
        start: null,
        duration: null,
      },
      show: { must: true, nice: true, params: true, process: true },
    },
    ...overrides,
  };
}

const URL = "https://kariera.b2bnetwork.pl/r/senior-java-developer-k7q2";

describe("jobPostingJsonLd", () => {
  it("buduje ofertę z opublikowanego opisu — bez klienta i stawek", () => {
    const ld = jobPostingJsonLd(data(), URL);
    expect(ld).toMatchObject({
      "@type": "JobPosting",
      title: "Senior Java Developer",
      datePosted: "2026-10-18",
      employmentType: "CONTRACTOR",
      hiringOrganization: { name: "B2B Network" },
      directApply: true,
      url: URL,
      jobLocation: { address: { addressLocality: "Warszawa", addressCountry: "PL" } },
    });
    expect(ld?.description).toContain("Wymagania: Java 17.");
    expect(ld?.description).toContain("Mile widziane: Kafka.");
    expect(JSON.stringify(ld)).not.toMatch(/baseSalary|zł|PLN/);
  });

  it("zdalna rekrutacja to praca zdalna z Polski, bez miejsca", () => {
    const base = data();
    const ld = jobPostingJsonLd(
      { ...base, job: { ...base.job, params: { ...base.job.params!, remote_policy: "remote" } } },
      URL,
    );
    expect(ld?.jobLocationType).toBe("TELECOMMUTE");
    expect(ld?.jobLocation).toBeUndefined();
  });

  it("zamknięta rekrutacja i brak daty publikacji nie dają danych", () => {
    expect(jobPostingJsonLd(data({ status: "closed" }), URL)).toBeNull();
    expect(jobPostingJsonLd(data({ published_at: null }), URL)).toBeNull();
  });

  it("tekst z „</script>” nie zamyka znacznika", () => {
    expect(jsonLdString({ a: "</script><b>" })).toBe('{"a":"\\u003c/script>\\u003cb>"}');
  });
});
