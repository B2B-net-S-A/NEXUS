import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExclusionWaterfall } from "@/components/v2/pages/CandidateSearchView";
import type { SearchDiagnosticsResponse } from "@/lib/candidate-search-api";

const diagnostics: SearchDiagnosticsResponse = {
  base_count: 54061,
  stages: [
    { key: "competence_category", label: "Kategoria kompetencji", count: 8420 },
    { key: "skills", label: "Umiejętności", count: 2110 },
    { key: "location", label: "Lokalizacja", count: 310 },
    { key: "rate_hourly", label: "Stawka godzinowa", count: 0 },
  ],
  total: 0,
  first_zeroing_stage: "rate_hourly",
};

describe("ExclusionWaterfall", () => {
  it("shows a spinner label while loading with no data yet", () => {
    render(<ExclusionWaterfall diagnostics={null} loading />);
    expect(screen.getByText(/Analizuję/i)).toBeInTheDocument();
  });

  it("falls back to a plain message when there are no stages", () => {
    render(
      <ExclusionWaterfall
        diagnostics={{ base_count: 100, stages: [], total: 0 }}
        loading={false}
      />,
    );
    expect(screen.getByText(/Zmień filtry/i)).toBeInTheDocument();
  });

  it("renders the base row plus every stage", () => {
    render(<ExclusionWaterfall diagnostics={diagnostics} loading={false} />);
    expect(screen.getByText("Wszyscy kandydaci")).toBeInTheDocument();
    expect(screen.getByText("Kategoria kompetencji")).toBeInTheDocument();
    expect(screen.getByText("Stawka godzinowa")).toBeInTheDocument();
    // base count rendered with pl-PL grouping (non-breaking space)
    expect(screen.getByText(/54\s?061/)).toBeInTheDocument();
  });

  it("marks the first zeroing stage as the culprit", () => {
    render(<ExclusionWaterfall diagnostics={diagnostics} loading={false} />);
    expect(screen.getByText(/← tutaj/)).toBeInTheDocument();
    expect(
      screen.getByText(/Poluzuj oznaczony filtr/i),
    ).toBeInTheDocument();
  });
});
