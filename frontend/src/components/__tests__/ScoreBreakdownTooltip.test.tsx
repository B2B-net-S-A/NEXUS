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
});
