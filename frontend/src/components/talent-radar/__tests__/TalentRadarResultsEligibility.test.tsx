/**
 * Radar: konflikt z klientem (czarna lista klienta / NDA / konkurent) od
 * 17.09.2026 nie wyklucza kandydata — karta pokazuje powód jako ostrzeżenie.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TalentRadarMeta, TalentRadarResult } from "@/lib/talent-radar-api";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { TalentRadarResults } from "@/components/talent-radar/TalentRadarResults";

const layer = { points: 0, max: 0, reason: "" };

function result(
  id: number,
  eligibility: TalentRadarResult["eligibility"],
): TalentRadarResult {
  return {
    candidate_id: id,
    total: 72,
    semantic: layer,
    skills: layer,
    salary: layer,
    location: layer,
    availability: layer,
    champion_fit: layer,
    matching_must: [],
    gap_must: [],
    matching_nice: [],
    gap_nice: [],
    penalties: [],
    warnings: eligibility ? ["active_conflict"] : [],
    fit_confidence: null,
    eligibility,
    candidate: {
      id,
      name: "Kandydat",
      lastname: `Nr${id}`,
      location: null,
      competence_category: null,
      years_it_experience: null,
      availability_status: null,
      champion: false,
      avatar_url: null,
    },
  } as TalentRadarResult;
}

const META: TalentRadarMeta = {
  pool_size: 2,
  eligible_size: 2,
  returned: 2,
  degraded: false,
  reason: null,
};

describe("TalentRadarResults — eligibility", () => {
  it("renders the client-conflict reason as a warning line and keeps the score", () => {
    render(
      <TalentRadarResults
        meta={META}
        pending={false}
        results={[
          result(1, {
            reason_code: "client_nda",
            reason: "Konflikt: NDA z klientem",
            assignment_allowed: true,
            visibility: "warn",
            severity: "warning",
            secondary: [],
          }),
          result(2, null),
        ]}
      />,
    );

    const line = screen.getByTestId("tr-eligibility-1");
    expect(line).toHaveTextContent("Konflikt: NDA z klientem");
    expect(line.className).toContain("warning");
    expect(screen.queryByTestId("tr-eligibility-2")).not.toBeInTheDocument();
  });

  it("pokazuje znacznik „Pracuje u nas” i nie dubluje go ostrzeżeniem o tym samym kliencie", () => {
    const employedAtThisClient = {
      reason_code: "client_current_employment",
      reason: "Kandydat obecnie pracuje u tego klienta",
      assignment_allowed: true,
      visibility: "warn",
      severity: "warning",
      secondary: [],
    } as TalentRadarResult["eligibility"];
    const client = {
      client_id: 5,
      client_name: "Bank Przykładowy",
      contract_id: 50,
      phase: "working" as const,
    };
    render(
      <TalentRadarResults
        meta={META}
        pending={false}
        results={[
          // Pracuje u klienta, dla którego szukamy: znacznik mówi to sam.
          {
            ...result(1, employedAtThisClient),
            employment_marker: { phase: "working", source: "contract", elsewhere: false, clients: [client] },
          },
          // Pracuje u innego klienta: sam znacznik, bez ostrzeżenia.
          {
            ...result(2, null),
            employment_marker: { phase: "working", source: "contract", elsewhere: true, clients: [client] },
          },
        ]}
      />,
    );

    expect(screen.getByText("Pracuje u tego klienta")).toBeInTheDocument();
    expect(screen.queryByTestId("tr-eligibility-1")).not.toBeInTheDocument();
    expect(screen.getByText("Pracuje u nas · Bank Przykładowy")).toBeInTheDocument();
  });
});
