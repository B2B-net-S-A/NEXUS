import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.fn();
const matchScores = vi.fn();

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    search: (...args: unknown[]) => search(...args),
    diagnostics: vi.fn(),
    matchScores: (...args: unknown[]) => matchScores(...args),
  },
  proposalsBulkApi: { assignableStages: () => Promise.resolve([]) },
  shortlistApi: {},
  savedSearchesApi: { list: () => Promise.resolve([]) },
}));

vi.mock("@/components/v2/filters/FiltersPanel", () => ({
  FiltersPanel: () => null,
}));
vi.mock("@/components/v2/pages/JobShortlistPanel", () => ({
  JobShortlistPanel: () => null,
}));
vi.mock("@/components/v2/pages/CandidateCompareModal", () => ({
  CandidateCompareModal: () => null,
}));

import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";

function item(id: number) {
  return {
    id,
    name: "Kandydat",
    lastname: `Nr${id}`,
    email: null,
    phone: null,
    location: null,
    status: "active",
    availability_status: null,
    source: null,
    competence_category: null,
    competence_category_id: null,
    availability_date: null,
    years_it_experience: null,
    tags: null,
    skills: null,
    languages: null,
    ai_summary: null,
    avatar_url: null,
    relevance_score: 0,
    has_cv: true,
    has_linkedin: false,
    is_champion: false,
    created_at: null,
    updated_at: null,
  };
}

describe("CandidateSearchView — canonical fit column", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search.mockResolvedValue({
      total: 50,
      page: 1,
      page_size: 50,
      items: Array.from({ length: 50 }, (_, i) => item(i + 1)),
      facets: { competence_categories: [] },
      meta: { ai_status: "ok", took_ms: 5 },
    });
    matchScores.mockResolvedValue({
      scores: { "1": 77 },
      breakdowns: {
        "1": { total: 77.4, measurement: "measured" },
        "2": { total: null, measurement: "stale" },
      },
    });
  });

  it("asks for at most 20 rows of a 50-row page and shows 'not measured' honestly", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <CandidateSearchView addToJob={{ id: 9, title: "Java" }} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(matchScores).toHaveBeenCalled());
    // jsdom has no IntersectionObserver → only the first screenful asks.
    expect(matchScores).toHaveBeenCalledTimes(1);
    const [jobId, ids] = matchScores.mock.calls[0] as [number, number[]];
    expect(jobId).toBe(9);
    expect(ids).toEqual(Array.from({ length: 20 }, (_, i) => i + 1));

    expect(await screen.findByRole("button", { name: /^77$/ })).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Ocena niepełna: profil kandydata zmienił się od ostatniej indeksacji",
      }),
    ).toBeInTheDocument();
  });

  it("outside a recruitment context never measures", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CandidateSearchView />
      </QueryClientProvider>,
    );

    await screen.findByText("Kandydat Nr1");
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(matchScores).not.toHaveBeenCalled();
  });
});
