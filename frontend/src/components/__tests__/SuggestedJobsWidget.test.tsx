import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import type { JobMatch, RecommendationMeta } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: ComponentProps<"a">) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  recommendationsApi: {
    forCandidate: vi.fn(),
    assignToJob: vi.fn(),
  },
}));

describe("SuggestedJobsWidget degraded recommendations", () => {
  it("renders BM25 as unscored instead of formatting null", async () => {
    const match: JobMatch = {
      job: {
        id: 11,
        title: "Python Developer",
        client_id: null,
        location: "Warszawa",
        salary_min: null,
        salary_max: null,
        remote_policy: null,
        status: "published",
        priority: null,
        seniority: null,
        industry: null,
        deadline: null,
      },
      total_score: null,
      breakdown: null,
    };
    const meta: RecommendationMeta = {
      mode: "bm25",
      degraded: true,
      reason: "semantic_unavailable",
    };

    render(
      <SuggestedJobsWidget
        candidateId={0}
        matches={[match]}
        recommendationMeta={meta}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "trybie awaryjnym BM25",
    );
    expect(screen.getByText("BM25 · tryb awaryjny")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
