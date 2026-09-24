import { describe, expect, it } from "vitest";

import type { ProposalFacts } from "@/lib/job-proposals-api";
import {
  clientHistoryLine,
  factsRateLabel,
  proposalFactsLine,
  sortByClientHistory,
  workModeLabel,
  yearsLabel,
} from "@/lib/proposal-facts";

const NOW = new Date("2026-09-24T10:00:00Z");

function facts(overrides: Partial<ProposalFacts> = {}): ProposalFacts {
  return {
    candidate_id: 1,
    title: null,
    company: null,
    years_experience: null,
    city: null,
    max_onsite_days_per_week: null,
    remote_modes: [],
    availability_status: null,
    availability_date: null,
    expected_rate_hourly: null,
    expected_rate_currency: null,
    expected_rate_redacted: false,
    client_history: null,
    ...overrides,
  };
}

describe("proposal-facts", () => {
  it("nieznane fakty znikają z linii — bez „stawka —” i myślników", () => {
    expect(proposalFactsLine(facts(), NOW)).toBeNull();
    expect(proposalFactsLine(facts({ title: "QA", city: "Łódź" }), NOW)).toBe("QA · Łódź");
    expect(
      proposalFactsLine(
        facts({
          title: "Java Developer",
          company: "Firma",
          years_experience: 5,
          city: "Gdańsk",
          max_onsite_days_per_week: 2,
          availability_date: "2026-09-01",
          expected_rate_hourly: 160,
          expected_rate_currency: "PLN",
        }),
        NOW,
      ),
    ).toBe("Java Developer @ Firma · 5 lat dośw. · Gdańsk · do 2 dni w biurze · od razu · 160 zł/h");
  });

  it("staż, tryb pracy i stawka po polsku", () => {
    expect(yearsLabel(1)).toBe("1 rok dośw.");
    expect(yearsLabel(3)).toBe("3 lata dośw.");
    expect(yearsLabel(0)).toBeNull();
    expect(workModeLabel({ max_onsite_days_per_week: 0, remote_modes: [] })).toBe("tylko zdalnie");
    expect(workModeLabel({ max_onsite_days_per_week: 1, remote_modes: [] })).toBe("do 1 dnia w biurze");
    expect(workModeLabel({ max_onsite_days_per_week: null, remote_modes: ["remote"] })).toBe("tylko zdalnie");
    expect(workModeLabel({ max_onsite_days_per_week: null, remote_modes: [] })).toBeNull();
    expect(factsRateLabel({ expected_rate_hourly: 30, expected_rate_currency: "EUR" })).toBe("30 EUR/h");
    expect(factsRateLabel({ expected_rate_hourly: null, expected_rate_currency: "PLN" })).toBeNull();
    // Import zapisywał walutę jako „zł” / „ZŁ” — to wciąż złotówki (produkcja 24.09: „60 ZŁ/h”).
    expect(factsRateLabel({ expected_rate_hourly: 60, expected_rate_currency: "ZŁ" })).toBe("60 zł/h");
    expect(factsRateLabel({ expected_rate_hourly: 60, expected_rate_currency: "zł" })).toBe("60 zł/h");
  });

  it("sama firma bez stanowiska — bez wiszącej „@”", () => {
    expect(proposalFactsLine(facts({ company: "Astek", city: "Warszawa" }), NOW)).toBe("Astek · Warszawa");
  });

  it("historia u klienta: rekrutacja, najdalszy etap i wynik", () => {
    expect(clientHistoryLine(null)).toBeNull();
    expect(
      clientHistoryLine({
        job_id: 7,
        title: "Senior Java",
        furthest_stage: "client_interview",
        furthest_stage_label: "Interview Klient",
        outcome: "withdrawn",
        last_moved_at: null,
      }),
    ).toBe("Był(a) u tego klienta: Senior Java — doszedł(a) do etapu „Interview Klient” (zrezygnował/a)");
  });

  it("sortowanie: najpierw byli u klienta (dalej = wyżej), reszta w dotychczasowej kolejności", () => {
    const rows = [1, 2, 3, 4].map((candidateId) => ({ candidateId }));
    const byId = new Map<number, ProposalFacts>([
      [3, facts({ candidate_id: 3, client_history: { job_id: 1, title: "A", furthest_stage: "verified", furthest_stage_label: "Zweryfikowany", outcome: "rejected", last_moved_at: null } })],
      [4, facts({ candidate_id: 4, client_history: { job_id: 2, title: "B", furthest_stage: "cv_sent", furthest_stage_label: "CV Wysłane", outcome: "rejected", last_moved_at: null } })],
    ]);
    expect(sortByClientHistory(rows, byId).map((r) => r.candidateId)).toEqual([4, 3, 1, 2]);
  });
});
