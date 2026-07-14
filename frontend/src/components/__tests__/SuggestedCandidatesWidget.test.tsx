import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  selectMatchesForHistory,
  SuggestedCandidatesWidget,
} from "@/components/SuggestedCandidatesWidget";
import type { CandidateMatch, RecommendationMeta, ScoreBreakdown } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  regenerate: vi.fn(),
  forJob: vi.fn(),
  assignToJob: vi.fn(),
  logHistory: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  proposalsApi: {
    latest: (...args: unknown[]) => mocks.latest(...args),
    regenerate: (...args: unknown[]) => mocks.regenerate(...args),
  },
  recommendationsApi: {
    forJob: (...args: unknown[]) => mocks.forJob(...args),
    assignToJob: (...args: unknown[]) => mocks.assignToJob(...args),
  },
  matchHistoryApi: {
    log: (...args: unknown[]) => mocks.logHistory(...args),
  },
}));

vi.mock("@/components/v2/filters/LocationInput", () => ({
  LocationInput: () => <input aria-label="Lokalizacja" />,
}));

vi.mock("@/components/v2/pages/candidate-list-helpers", () => ({
  formatCandidateLocation: (value: string | null) => value,
}));

const BREAKDOWN: ScoreBreakdown = {
  candidate_id: 42,
  job_id: 7,
  total: 82,
  semantic: { points: 35, max: 40, reason: "high similarity" },
  skills: { points: 25, max: 30, reason: "must skills" },
  salary: { points: 10, max: 15, reason: "in range" },
  location: { points: 8, max: 10, reason: "same city" },
  availability: { points: 4, max: 5, reason: "available" },
  matching_must: ["Python"],
  gap_must: [],
  matching_nice: [],
  gap_nice: [],
  penalties: [],
};

function candidateMatch(
  totalScore: number | null,
  breakdown: ScoreBreakdown | null = null,
): CandidateMatch {
  return {
    candidate: {
      id: 42,
      name: "Anna",
      lastname: "Nowak",
      email: null,
      location: "Warszawa",
      champion: false,
      salary_expectation: null,
      salary_currency: null,
      years_it_experience: 6,
      competence_category: "Backend",
    },
    total_score: totalScore,
    breakdown,
  };
}

function renderWidget() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SuggestedCandidatesWidget jobId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.latest.mockRejectedValue({ response: { status: 404 } });
  mocks.regenerate.mockResolvedValue({ data: {} });
  mocks.assignToJob.mockResolvedValue({ data: {} });
});

describe("SuggestedCandidatesWidget degraded recommendations", () => {
  it("renders BM25 explicitly without formatting null as a numeric score", async () => {
    mocks.forJob.mockResolvedValue({
      data: {
        job_id: 7,
        job_title: "Backend Developer",
        search_type: "hybrid",
        matches: [candidateMatch(null)],
        meta: {
          mode: "bm25",
          degraded: true,
          reason: "semantic_unavailable",
        },
      },
    });

    renderWidget();
    fireEvent.click(await screen.findByTestId("suggest-candidates-btn"));

    expect(await screen.findByTestId("degraded-recommendations-notice")).toHaveTextContent(
      "trybie awaryjnym BM25",
    );
    expect(screen.getByTestId("degraded-score-42")).toHaveTextContent(
      "BM25 · tryb awaryjny",
    );
    expect(screen.queryByText("0/100")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.logHistory).not.toHaveBeenCalled());
  });

  it("filters unscored and explicitly degraded results out of match history", () => {
    const normalMeta: RecommendationMeta = {
      mode: "dense",
      degraded: false,
      reason: null,
    };
    const degradedMeta: RecommendationMeta = {
      mode: "bm25",
      degraded: true,
      reason: "semantic_unavailable",
    };
    const scored = candidateMatch(82, BREAKDOWN);
    const unscored = candidateMatch(null);

    expect(selectMatchesForHistory([unscored, scored], normalMeta)).toEqual([scored]);
    expect(selectMatchesForHistory([scored], degradedMeta)).toEqual([]);
  });
});
