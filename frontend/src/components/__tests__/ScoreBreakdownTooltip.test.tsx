import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ScoreBreakdownTooltip } from "@/components/ScoreBreakdownTooltip";
import type { ScoreBreakdown } from "@/lib/api";

const FIXTURE: ScoreBreakdown = {
  candidate_id: 42,
  job_id: 7,
  total: 78.5,
  semantic: { points: 35, max: 40, reason: "high similarity" },
  skills: { points: 25, max: 30, reason: "must 4/5" },
  salary: { points: 10, max: 15, reason: "near range" },
  location: { points: 6, max: 10, reason: "same city" },
  availability: { points: 3, max: 5, reason: "available soon" },
  matching_must: ["python", "fastapi", "postgres"],
  gap_must: ["kubernetes"],
  matching_nice: ["docker"],
  gap_nice: [],
  penalties: [],
};

describe("ScoreBreakdownTooltip", () => {
  it("renders trigger with 'dlaczego ? ' label", () => {
    render(<ScoreBreakdownTooltip breakdown={FIXTURE} />);
    expect(screen.getByText(/dlaczego/i)).toBeInTheDocument();
  });

  it("opens details on click and shows total + matching_must", () => {
    render(<ScoreBreakdownTooltip breakdown={FIXTURE} />);
    fireEvent.click(screen.getByRole("button"));
    // Total is displayed with one decimal
    expect(screen.getByText("78.5")).toBeInTheDocument();
    // Must matches shown as chips
    expect(screen.getByText(/✓ python/i)).toBeInTheDocument();
    expect(screen.getByText(/✓ fastapi/i)).toBeInTheDocument();
    // Gap shown with ✗
    expect(screen.getByText(/✗ kubernetes/i)).toBeInTheDocument();
  });

  it("shows penalties section when present", () => {
    const withPenalty: ScoreBreakdown = {
      ...FIXTURE,
      total: 0,
      penalties: ["blacklisted"],
    };
    render(<ScoreBreakdownTooltip breakdown={withPenalty} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/penalties/i)).toBeInTheDocument();
    expect(screen.getByText(/blacklisted/)).toBeInTheDocument();
  });

  it("shows process history separately without bonus points", () => {
    const withBoost: ScoreBreakdown = {
      ...FIXTURE,
      total: 83.5,
      historical_boost: 0,
      historical_sources_count: 2,
    };
    render(<ScoreBreakdownTooltip breakdown={withBoost} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Historia")).toBeInTheDocument();
    expect(screen.getByText(/bez wpływu na wynik/)).toBeInTheDocument();
    expect(screen.queryByText(/\+.*pkt/)).not.toBeInTheDocument();
    expect(screen.getByText(/2 podobn/)).toBeInTheDocument();
  });

  it("hides historical boost row when absent or zero", () => {
    render(<ScoreBreakdownTooltip breakdown={FIXTURE} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.queryByText("Historia")).not.toBeInTheDocument();
  });

  it("identifies a legacy bonus rather than claiming old totals exclude history", () => {
    render(<ScoreBreakdownTooltip breakdown={{ ...FIXTURE, historical_boost: 10, historical_sources_count: 2 }} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/archiwalny bonus \+10.0 pkt — przelicz ocenę/)).toBeInTheDocument();
    expect(screen.queryByText(/bez wpływu na wynik/)).not.toBeInTheDocument();
  });
});
