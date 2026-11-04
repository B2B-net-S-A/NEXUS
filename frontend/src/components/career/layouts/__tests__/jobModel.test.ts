import { describe, expect, it } from "vitest";

import type { CareerJobResponse } from "@/lib/career/api";

import { mockJob } from "../jobModel";

function response(job: Partial<CareerJobResponse["job"]> = {}): CareerJobResponse {
  return {
    status: "open",
    recruiter: { first_name: "Marta", slug: "marta-n" },
    theme: "grafit",
    job: {
      slug: "kyc-delivery-lead-ab12",
      title: "  KYC Delivery Lead ",
      subtitle: " ",
      about:
        "Projekt dotyczy wdrożenia pakietu AML.\n\nCzym się zajmiesz: planowanie strumieni prac; definiowanie zakresu; raportowanie postępów.",
      must: [{ name: "KYC", note: null }],
      nice: ["Transaction Monitoring"],
      params: {
        city: "Gdańsk, Warszawa",
        remote_policy: "hybrid",
        onsite_days_per_week: 3,
        seniority: "senior",
        contract: "B2B",
        start: null,
        duration: null,
      },
      show: { must: true, nice: true, params: true, process: true },
      ...job,
    },
  };
}

describe("model ogłoszenia (szablony 28.10.2026)", () => {
  it("„Czym się zajmiesz: a; b; c” staje się nagłówkiem i punktami", () => {
    const { about } = mockJob(response());
    expect(about[0]).toEqual({
      heading: null,
      text: "Projekt dotyczy wdrożenia pakietu AML.",
      bullets: [],
    });
    expect(about[1]).toEqual({
      heading: "Czym się zajmiesz",
      text: null,
      bullets: ["Planowanie strumieni prac", "Definiowanie zakresu", "Raportowanie postępów"],
    });
  });

  it("akapit z dwiema częściami po średniku zostaje akapitem", () => {
    const { about } = mockJob(response({ about: "Zespół: pięć osób; dwa kraje." }));
    expect(about).toEqual([{ heading: "Zespół", text: "pięć osób; dwa kraje.", bullets: [] }]);
  });

  it("fakty z wielkiej litery, tryb hybrydowy z dniami w biurze", () => {
    const job = mockJob(response());
    expect(job.facts.map((f) => [f.label, f.value])).toEqual([
      ["Lokalizacja", "Gdańsk, Warszawa"],
      ["Tryb pracy", "Hybryda · 3 dni w biurze w tygodniu"],
      ["Umowa", "B2B"],
      ["Poziom", "Senior"],
    ]);
    expect(job.title).toBe("KYC Delivery Lead");
    expect(job.subtitle).toBeNull();
  });

  it("ukryte parametry i sekcje nie zostawiają pustych faktów ani list", () => {
    const job = mockJob(
      response({ show: { must: false, nice: false, params: false, process: false } }),
    );
    expect(job.facts).toEqual([]);
    expect(job.factsLine).toBe("");
    expect(job.must).toEqual([]);
    expect(job.nice).toEqual([]);
    expect(job.steps).toEqual([]);
  });

  it("brak parametrów i opisu", () => {
    const job = mockJob(response({ params: null, about: null }));
    expect(job.facts).toEqual([]);
    expect(job.about).toEqual([]);
    expect(job.steps).toHaveLength(4);
  });
});
