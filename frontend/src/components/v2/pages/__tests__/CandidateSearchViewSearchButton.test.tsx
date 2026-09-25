import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.fn();
let urlParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    search: (...args: unknown[]) => search(...args),
    diagnostics: vi.fn(() => Promise.resolve({ base_count: 0, stages: [], total: 0, first_zeroing_stage: null })),
    matchScores: vi.fn(() => Promise.resolve({ scores: {}, breakdowns: {} })),
  },
  proposalsBulkApi: { assignableStages: () => Promise.resolve([]) },
  shortlistApi: {},
  savedSearchesApi: { list: () => Promise.resolve([]) },
}));

vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: {
    get: vi.fn(() => Promise.resolve({ groups: [] })),
  },
  requirementLabels: () => [],
}));

// Panel filtrów zastąpiony dwoma przyciskami: zmiana szkicu i „Szukaj”.
vi.mock("@/components/v2/filters/FiltersPanel", () => ({
  FiltersPanel: ({
    value,
    onChange,
    onSearch,
    pendingCount,
  }: {
    value: { q?: string | null };
    onChange: (next: unknown) => void;
    onSearch?: () => void;
    pendingCount?: number;
  }) => (
    <div>
      <span data-testid="draft-q">{value.q ?? ""}</span>
      <span data-testid="pending">{pendingCount ?? 0}</span>
      <button type="button" onClick={() => onChange({ ...value, q: "kafka" })}>
        zmień szkic
      </button>
      <button type="button" onClick={() => onSearch?.()}>
        szukaj
      </button>
    </div>
  ),
}));
vi.mock("@/components/v2/pages/JobShortlistPanel", () => ({
  JobShortlistPanel: () => null,
}));

import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";
import { clearSearchMemory } from "@/lib/search-memory";
import { useAuthStore } from "@/store/auth";

function emptyPage() {
  return {
    total: 0,
    page: 1,
    page_size: 50,
    items: [],
    facets: { competence_categories: [] },
    meta: { ai_status: "ok", took_ms: 1 },
  };
}

function renderView(props: Parameters<typeof CandidateSearchView>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateSearchView {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  search.mockReset().mockResolvedValue(emptyPage());
  urlParams = new URLSearchParams();
  clearSearchMemory();
  useAuthStore.setState({ user: { id: 7 } } as never);
});

afterEach(() => clearSearchMemory());

describe("CandidateSearchView — przycisk „Szukaj”", () => {
  it("zmiana w panelu czeka na „Szukaj”, a potem idzie do API", async () => {
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "zmień szkic" }));
    expect(screen.getByTestId("pending").textContent).toBe("1");
    expect(await screen.findByText("1 zmiana czeka na „Szukaj”")).toBeTruthy();
    await new Promise((r) => setTimeout(r, 400));
    expect(search).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "szukaj" }));
    await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
    expect(search.mock.calls[1][0]).toMatchObject({ q: "kafka", page: 1 });
    expect(screen.getByTestId("pending").textContent).toBe("0");
  });

  it("„Cofnij zmiany” wraca do zastosowanego wyszukiwania", async () => {
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "zmień szkic" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cofnij zmiany" }));
    expect(screen.getByTestId("draft-q").textContent).toBe("");
    expect(screen.getByTestId("pending").textContent).toBe("0");
  });
});
