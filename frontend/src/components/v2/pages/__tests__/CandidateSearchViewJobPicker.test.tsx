import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  matchScores: vi.fn(),
  bulkAdd: vi.fn(),
  jobGet: vi.fn(),
  canAdd: true,
}));
let urlParams = new URLSearchParams();

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

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    search: (...args: unknown[]) => mocks.search(...args),
    diagnostics: vi.fn(() => Promise.resolve(null)),
    matchScores: (...args: unknown[]) => mocks.matchScores(...args),
  },
  proposalsBulkApi: {
    assignableStages: () => Promise.resolve([]),
    add: (...args: unknown[]) => mocks.bulkAdd(...args),
  },
  shortlistApi: {},
  savedSearchesApi: { list: () => Promise.resolve([]) },
}));

vi.mock("@/lib/api", () => ({
  jobsApi: { get: (...args: unknown[]) => mocks.jobGet(...args) },
}));

vi.mock("@/components/v2/recruitment/JobPicker", () => ({
  JobPicker: ({ onChange }: { onChange: (job: { id: number; title: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 42, title: "Java Developer" })}>
      Wybierz Java Developer (mock)
    </button>
  ),
}));

vi.mock("@/components/v2/recruitment/useCanAddToRecruitment", () => ({
  useCanAddToRecruitment: () => mocks.canAdd,
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

function item(id: number, availability_status: string | null = null) {
  return {
    id,
    name: "Kandydat",
    lastname: `Nr${id}`,
    email: null,
    phone: null,
    location: null,
    status: "active",
    availability_status,
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

function renderView(props: { syncUrl?: boolean } = {}) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CandidateSearchView backHref="/candidates" {...props} />
    </QueryClientProvider>,
  );
}

describe("CandidateSearchView — rekrutacja w samodzielnej wyszukiwarce (B5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.canAdd = true;
    urlParams = new URLSearchParams();
    window.history.replaceState(null, "", "/candidates/search");
    mocks.search.mockResolvedValue({
      total: 2,
      page: 1,
      page_size: 50,
      items: [item(1, "unknown"), item(2, "open_to_offers")],
      facets: { competence_categories: [] },
      meta: { ai_status: "ok", took_ms: 1 },
    });
    mocks.matchScores.mockResolvedValue({
      scores: { "1": 81 },
      breakdowns: { "1": { total: 81, measurement: "measured" } },
      profile_key: "0:default",
    });
    mocks.bulkAdd.mockResolvedValue({ added: [1], skipped: [], total_added: 1, total_skipped: 0 });
    mocks.jobGet.mockResolvedValue({ data: { id: 42, title: "Java Developer", client_name: "Bank" } });
  });

  it("bez rekrutacji nie ma oceny ani zaznaczania; etykiety dostępności są po polsku", async () => {
    renderView({ syncUrl: true });
    expect(await screen.findByText("Nieznane")).toBeInTheDocument();
    expect(screen.getByText("Otwarty na oferty")).toBeInTheDocument();
    expect(screen.queryByText(/unknown/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(mocks.matchScores).not.toHaveBeenCalled();
  });

  it("wybrana rekrutacja włącza ocenę, zaznaczanie i dodanie jako manual_search", async () => {
    renderView({ syncUrl: true });
    await screen.findByText("Nieznane");

    fireEvent.click(screen.getByRole("button", { name: "Wybierz rekrutację" }));
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));

    await waitFor(() =>
      expect(mocks.search).toHaveBeenLastCalledWith(
        expect.objectContaining({ exclude_in_job_id: 42, page: 1 }),
        expect.any(AbortSignal),
      ),
    );
    expect(screen.getByTestId("search-picked-job")).toHaveTextContent("Java Developer");
    expect(window.location.search).toContain("job=42");

    await waitFor(() => expect(mocks.matchScores).toHaveBeenCalled());
    expect(mocks.matchScores.mock.calls[0][0]).toBe(42);
    expect(await screen.findByRole("button", { name: /^81$/ })).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Kandydat Nr1" }));
    fireEvent.click(screen.getByRole("button", { name: /Dodaj do „Java Developer"/ }));
    await waitFor(() => expect(mocks.bulkAdd).toHaveBeenCalled());
    expect(mocks.bulkAdd.mock.calls[0][0]).toBe(42);
    expect(mocks.bulkAdd.mock.calls[0][1]).toMatchObject({ candidate_ids: [1], source: "manual_search" });
    // Shortlista ma panel tylko na stronie rekrutacji.
    expect(screen.queryByRole("button", { name: /Do shortlisty/ })).not.toBeInTheDocument();
  });

  it("?job= z URL-a przywraca rekrutację i dociąga jej tytuł", async () => {
    urlParams = new URLSearchParams("job=42");
    renderView({ syncUrl: true });
    await waitFor(() =>
      expect(mocks.search).toHaveBeenCalledWith(
        expect.objectContaining({ exclude_in_job_id: 42 }),
        expect.any(AbortSignal),
      ),
    );
    expect(mocks.jobGet).toHaveBeenCalledWith(42);
    expect(await screen.findByText("Java Developer · Bank")).toBeInTheDocument();
  });

  it("rola bez prawa dodawania widzi ocenę, ale nie przycisk dodania", async () => {
    mocks.canAdd = false;
    urlParams = new URLSearchParams("job=42");
    renderView({ syncUrl: true });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Kandydat Nr1" }));
    expect(screen.queryByRole("button", { name: /Dodaj do „/ })).not.toBeInTheDocument();
  });

  it("„Wyczyść” zdejmuje rekrutację z wyszukiwania i z URL-a", async () => {
    urlParams = new URLSearchParams("job=42");
    renderView({ syncUrl: true });
    await screen.findByText("Java Developer · Bank");
    fireEvent.click(screen.getByRole("button", { name: "Wyczyść rekrutację" }));
    await waitFor(() =>
      expect(mocks.search.mock.lastCall?.[0]).not.toHaveProperty("exclude_in_job_id"),
    );
    expect(window.location.search).not.toContain("job=");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
