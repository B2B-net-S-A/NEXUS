/**
 * Raport źródeł mówi, jak liczy i czego nie obejmuje (audyt statystyk
 * 14.09.2026, A05): model „każdy kontakt”, liczba unikalnych osób, udział
 * nowych kandydatów bez źródła i źródła bez daty poza okresem.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourcesCoverageNote } from "@/components/insights/sections/SourcesFunnelSection";
import type { SourceReportResponse } from "@/lib/api";

function report(overrides: Partial<SourceReportResponse> = {}): SourceReportResponse {
  return {
    period_start: "2026-08-16T00:00:00Z",
    period_end: "2026-09-15T00:00:00Z",
    rows: [],
    attribution_model: "multi_touch",
    unique_candidates: 12,
    new_candidates_total: 40,
    new_candidates_without_source: 10,
    undated_source_events: 0,
    ...overrides,
  };
}

describe("SourcesCoverageNote", () => {
  it("names the multi-touch model and the unique candidate count", () => {
    render(<SourcesCoverageNote data={report()} />);
    expect(screen.getByText(/wiersze się nie sumują/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("shows the share of new candidates without a source", () => {
    render(<SourcesCoverageNote data={report()} />);
    expect(screen.getByText("10 z 40 (25%)")).toBeInTheDocument();
  });

  it("renders a dash, not 0%, when no candidates were added", () => {
    render(
      <SourcesCoverageNote
        data={report({ new_candidates_total: 0, new_candidates_without_source: 0 })}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
  });

  it("explains undated Traffit sources only when there are any", () => {
    const { rerender } = render(<SourcesCoverageNote data={report()} />);
    expect(screen.queryByText(/nie ma daty/)).not.toBeInTheDocument();

    rerender(<SourcesCoverageNote data={report({ undated_source_events: 7 })} />);
    expect(
      screen.getByText("7 źródeł z Traffita nie ma daty — nie wchodzą do okresu."),
    ).toBeInTheDocument();
  });
});
