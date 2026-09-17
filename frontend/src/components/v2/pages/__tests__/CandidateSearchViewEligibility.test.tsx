import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
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

const NDA = {
  reason_code: "client_nda",
  reason: "Konflikt: NDA z klientem",
  assignment_allowed: true,
  visibility: "warn",
  severity: "warning",
  secondary: [],
};
const VETO = {
  reason_code: "rejected_by_hiring_manager",
  reason: "Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie",
  assignment_allowed: false,
  visibility: "warn",
  severity: "hard",
  secondary: [],
};

function item(id: number, eligibility: unknown = null) {
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
    eligibility,
  };
}

function renderView() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CandidateSearchView addToJob={{ id: 9, title: "Java" }} />
    </QueryClientProvider>,
  );
}

describe("CandidateSearchView — eligibility in a recruitment context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search.mockResolvedValue({
      total: 3,
      page: 1,
      page_size: 50,
      items: [item(1, NDA), item(2, VETO), item(3)],
      facets: { competence_categories: [] },
      meta: { ai_status: "ok", took_ms: 5 },
    });
    matchScores.mockResolvedValue({ scores: {}, breakdowns: {} });
  });

  it("a client conflict is a warning chip and the row stays selectable", async () => {
    renderView();
    const chip = await screen.findByTestId("search-eligibility-1");
    expect(chip).toHaveTextContent("Konflikt: NDA z klientem");
    expect(chip.className).toContain("warning");

    const checkbox = screen.getByRole("checkbox", { name: "Zaznacz Kandydat Nr1" });
    expect(checkbox).toBeEnabled();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("a hiring-manager veto disables the checkbox with the reason as title", async () => {
    renderView();
    const chip = await screen.findByTestId("search-eligibility-2");
    expect(chip.className).toContain("destructive");

    const checkbox = screen.getByRole("checkbox", { name: "Zaznacz Kandydat Nr2" });
    expect(checkbox).toBeDisabled();
    expect(checkbox).toHaveAttribute("title", VETO.reason);
    fireEvent.click(checkbox);
    expect(checkbox).not.toBeChecked();
  });

  it("a clean candidate has no chip", async () => {
    renderView();
    await screen.findByTestId("search-eligibility-1");
    expect(screen.queryByTestId("search-eligibility-3")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Kandydat Nr3" })).toBeEnabled();
  });
});
