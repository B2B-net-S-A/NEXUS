import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateNotesInsightsCard } from "../CandidateNotesInsightsCard";

describe("CandidateNotesInsightsCard", () => {
  it("renderuje null bez ekstrakcji (karta znika, zero pustego stanu)", () => {
    const { container: none } = render(
      <CandidateNotesInsightsCard insights={null} />,
    );
    expect(none.innerHTML).toBe("");

    // Payload istnieje, ale wszystkie pola puste/nullowe — też nic.
    const { container: empty } = render(
      <CandidateNotesInsightsCard
        insights={{
          skills_evidenced: [],
          expected_rate: { raw: null, value: null },
          availability: { available_from: null, notice_period: null, raw: null },
          current_engagement: {
            raw: null,
            ends_at: null,
            project: null,
            employer: null,
          },
          certifications: null,
          contract_form_preference: null,
        }}
      />,
    );
    expect(empty.innerHTML).toBe("");
  });

  it("renderuje umiejętności z dowodami, braki i wiersze faktów", () => {
    render(
      <CandidateNotesInsightsCard
        insights={{
          _v2_extracted_at: "2026-08-16T21:03:00Z",
          skills_evidenced: [
            { name: "SQL", evidence: "Na co dzień analiza danych w SQL" },
            { name: "REST API" },
          ],
          skills_gaps_observed: [{ name: "Remedy", evidence: "Nie pracował" }],
          expected_rate: {
            raw: "95 zł netto/h",
            value: 95,
            currency: "PLN",
            period: "h",
            as_of: "2026-07",
          },
          rate_flexibility: "Stawka bazowa 130 zł/h",
          availability: { notice_period: "1 miesiąc" },
          not_looking_until: "2026-07-31",
          contract_form_preference: "B2B",
          relocation: { willing: true, targets: ["Warszawa"] },
          preferences: {
            remote_only: true,
            locations: ["Wrocław"],
            sectors_prefer: ["finanse"],
            sectors_avoid: [],
            other: null,
          },
          languages_observed: [{ name: "English", level: "C1" }],
          years_confirmed: 14,
        }}
      />,
    );

    expect(screen.getByText("Z notatek rekruterskich")).toBeInTheDocument();
    expect(screen.getByText("ekstrakcja 2026-08-16")).toBeInTheDocument();
    expect(
      screen.getByText(/Potwierdzone umiejętności \(2\)/),
    ).toBeInTheDocument();
    expect(screen.getByText("SQL")).toBeInTheDocument();
    expect(screen.getByText("REST API")).toBeInTheDocument();
    expect(screen.getByText(/Zaobserwowane braki \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Remedy")).toBeInTheDocument();
    expect(screen.getByText("95 zł netto/h")).toBeInTheDocument();
    expect(screen.getByText("(stan: 2026-07)")).toBeInTheDocument();
    expect(screen.getByText("Stawka bazowa 130 zł/h")).toBeInTheDocument();
    expect(screen.getByText("wypowiedzenie 1 miesiąc")).toBeInTheDocument();
    expect(screen.getByText("2026-07-31")).toBeInTheDocument();
    expect(screen.getByText("B2B")).toBeInTheDocument();
    expect(screen.getByText("tak — Warszawa")).toBeInTheDocument();
    expect(screen.getByText("tylko zdalnie")).toBeInTheDocument();
    expect(screen.getByText("Wrocław")).toBeInTheDocument();
    expect(screen.getByText("English (C1)")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
  });

  it("zwija długą listę umiejętności do 12 chipów z przyciskiem rozwinięcia", () => {
    const skills = Array.from({ length: 20 }, (_, i) => ({
      name: `Skill-${i}`,
    }));
    render(<CandidateNotesInsightsCard insights={{ skills_evidenced: skills }} />);

    expect(screen.getByText("Skill-0")).toBeInTheDocument();
    expect(screen.queryByText("Skill-15")).not.toBeInTheDocument();
    const expand = screen.getByRole("button", { name: "+8 więcej" });
    expand.click();
  });

  it("nie pokazuje wet klientów ani matching_facts (poza zakresem karty)", () => {
    render(
      <CandidateNotesInsightsCard
        insights={
          {
            skills_evidenced: [{ name: "SQL" }],
            client_vetoes: [{ client: "Bank X", raw: "veto" }],
            matching_facts: ["fakt wewnętrzny"],
          } as never
        }
      />,
    );
    expect(screen.queryByText(/Bank X/)).not.toBeInTheDocument();
    expect(screen.queryByText(/fakt wewnętrzny/)).not.toBeInTheDocument();
  });
});
